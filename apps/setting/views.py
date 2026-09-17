import logging
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Min, Max, Exists, OuterRef, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.news.models import DeletedNewsRecord, Insight, News, TagCorrectionRecord
from apps.news.services import correct_news_tag, delete_news_with_record
from apps.reports.models import Report
from services.cleanup_prefilter import AI_KEYWORDS, should_prefilter_delete
from services.pricing import PRICE_PER_MILLION_TOKENS_USD, USD_KRW, compute_cost_krw
from .models import (
    DataSource, Keyword, CollectionLog, SlackConfig,
    Organization, TechTopic, OrgRelation, RunJob, RunProposal, RunDraft,
)

logger = logging.getLogger(__name__)

# SET-006 검증 파이프라인 현황 "stale" 임계값(일). PD 판단값이며 고정 정책이 아니다
# (docs/design.md SET-006 절 — 임계값 조정 시 이 상수만 바꾸면 된다).
UNVERIFIED_STALE_DAYS = 2


def _setting_menu(active):
    items = [
        # 최상단 — 매일 쓰는 항목이라 맨 아래에 묻히면 안 된다(docs/design.md SET-010
        # "진입점" 표, templates/setting/run.html PE 인계 절).
        {"label": "실행",       "icon": "play-circle",    "name": "setting_run",           "key": "run"},
        {"label": "데이터 소스", "icon": "database",      "name": "setting_sources",       "key": "sources"},
        {"label": "키워드",     "icon": "tag",            "name": "setting_keywords",      "key": "keywords"},
        {"label": "기업",       "icon": "building-2",     "name": "setting_organizations", "key": "organizations"},
        {"label": "기술 주제",  "icon": "cpu",            "name": "setting_tech_topics",   "key": "tech_topics"},
        {"label": "Slack",      "icon": "slack",          "name": "setting_slack",         "key": "slack"},
        # 라벨 "소식" (2026-09-04) — 사용자 대상 화면(ROOM-001/002)이 "뉴스룸"이라는
        # 낱말을 이미 걷어냈고(templates/newsroom/*.html), 그 화면들의 빈 상태 안내
        # 문구가 "설정 > 소식에서…"라고 말하므로 이 라벨도 맞춰야 안내가 실제로 길을
        # 가리킨다(templates/base.html newsroom_nav 계약 "함께 바꿔야 할 한 곳").
        # URL 이름(setting_newsroom)과 화면 ID(SET-009)는 그대로다.
        {"label": "소식",       "icon": "radio",          "name": "setting_newsroom",      "key": "newsroom"},
        {"label": "로그",       "icon": "scroll-text",    "name": "setting_logs",          "key": "logs"},
    ]
    for item in items:
        item["url"] = reverse(item["name"])
        item["active"] = item["key"] == active
    return items


class SettingLoginView(auth_views.LoginView):
    """`/login/` (config/urls.py) — templates/registration/login.html PE 인계 절 구현.

    base_setting.html을 상속하는 화면이라 좌측 설정 메뉴(setting_menu)가 없으면
    빈 흰 상자만 남는다(같은 템플릿 주석 🔴 참고) — 그래서 여기서 반드시 내려 준다.
    활성 항목은 없다(`_setting_menu(None)`) — 로그인 화면 자체는 메뉴 여덟 항목
    중 하나가 아니다.

    🔴 2026-09-17 PE 정리 — `next_label`을 계산하던 코드를 걷어냈다. 사용자가
    로그인 화면의 그 안내 줄을 빼라고 지시해 템플릿에서 먼저 뺐고(PD), 뷰만 계속
    계산해 아무도 읽지 않는 죽은 코드로 남아 있었다. `next` 파라미터 자체(로그인
    뒤 복귀 동작)는 그대로 쓴다 — `AuthenticationForm`/`LoginView`가 표준으로
    처리하므로 여기서 따로 다룰 것이 없다.
    """

    template_name = "registration/login.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["setting_menu"] = _setting_menu(None)
        return context


def _source_context():
    return {"sources": DataSource.objects.all()}


def sources(request):
    return render(request, "setting/sources.html", {
        "setting_menu": _setting_menu("sources"),
        **_source_context(),
    })


# --- SET-010 실행 (수동 LLM 실행 + 휴먼 인 더 루프) ---
# docs/design.md "SET-010 · 실행" 절, templates/setting/run.html 상단 {% comment %}이
# 정본 컨텍스트 계약이다.
#
# 🔴 2026-09-14 개정 — "1번을 LLM으로 옮기는 설계"의 1라운드(실행 뼈대)가 여기 들어왔다.
# 1단계 수집(양쪽 축 모두)이 이제 services/runner.py의 워커 스레드로 돈다 — 더 이상
# 요청 안에서 끝까지 동기로 돌지 않는다(EC2 gunicorn --timeout 60에 걸리던 위험, 문서
# 3-(d)). cleanup 등 나머지 단계는 여전히 services/llm.py가 비어 있어 비활성이다.
# RunJob·RunProposal 모델은 이번 라운드에 함께 세웠지만 RunProposal 행은 아직 만들지
# 않는다(2라운드 몫).
#
# 🔴 2026-09-04 개정 — jobs 하나가 research_jobs(AI 시장 조사 축)와
# newsroom_jobs(교보 소식 축) 둘로 갈렸다(사용자 지시, run.html 상단 계약 참고).
# 두 축의 job 키가 URL(setting/run/<job>/start/)에 그대로 들어가므로 이름이
# 겹치면 안 된다 — 그래서 교보 소식 쪽에 newsroom_ 접두어를 붙였다.

RESEARCH_JOB_KEYS = ("collect", "cleanup", "insight", "weekly", "monthly")
NEWSROOM_JOB_KEYS = ("newsroom_collect", "newsroom_filter", "newsroom_compose", "newsroom_send")
RUN_JOB_KEYS = RESEARCH_JOB_KEYS + NEWSROOM_JOB_KEYS

# "재료가 없다"와 "아직 만들지 않았다"는 다른 이유다(오케스트레이터 지시) — 미구현
# 단계는 전부 후자이므로, 재료 건수를 세는 코드를 만들지 않고 이 고정 문구 하나만 쓴다.
# run.html 상단 계약의 block_reason 예시 문구를 그대로 따른다.
NOT_IMPLEMENTED_REASON = "아직 만들지 않은 기능이에요"

# 라벨은 _run_graph.html의 include 태그(label=)가 정본이고, 여기 RUN_JOB_LABELS는
# run_review.html의 job_label(검토 화면 제목)에만 쓰인다 — 화면과 어긋나면 안 되므로
# _run_graph.html 상단 "노드 라벨 한곳 관리" 표와 같은 문구를 그대로 옮겼다.
RUN_JOB_LABELS = {
    "collect": "1단계 수집",
    "cleanup": "2단계 관련성 판정",
    "insight": "3단계 주요 이슈",
    "weekly": "4단계 주간 보고서",
    "monthly": "5단계 월간 보고서",
    "newsroom_collect": "1단계 수집",
    "newsroom_filter": "2단계 기사 선별",
    "newsroom_compose": "3단계 브리핑 작성",
    "newsroom_send": "4단계 발송",
}

# 완료(STATUS_DONE)여도 휴먼 인 더 루프가 있는 job은 사람이 확정을 누르기 전까지 "검토
# 대기"로 보여야 한다(apps/setting/models.py RunJob docstring "완료와 확정됨을 반드시
# 구분한다" 원칙). 휴먼 인 더 루프가 없는 collect/newsroom_collect는 이 목록에 넣지 않는다
# — 그 둘은 STATUS_DONE이 곧 "더 할 일 없음"이다.
# 🔴 2026-09-15 PE 개정 — "insight"를 추가했다. _run_review_context()가 _job_run_state()를
# 그대로 불러 검토 화면 머리글 상태를 만들므로, 여기 없으면 초안이 쌓인 배치도 review
# 화면에서 "완료"로 잘못 찍힌다.
# 🔴 2026-09-15 2라운드 — 메인 그래프(_research_jobs_context)도 이번에 insight 버튼을
# 열었다(선행 잠금 _insight_block_reason()과 함께). 위 문단이 말하는 "검토 대기" 전환은
# 그 버튼이 열렸든 닫혔든 GATED_JOB_KEYS만 보고 동작하므로 이 상수 자체는 그대로다.
#
# 🔴 같은 날 뒤이은 라운드 — "weekly"·"monthly"를 더한다(4, 5단계). 둘 다 확정하면
# Report가 실제로 생기는 휴먼 인 더 루프가 있으므로 완료 즉시가 아니라 검토 대기를 거친다.
GATED_JOB_KEYS = ("cleanup", "insight", "weekly", "monthly")

# SET-010 검토 화면(run_review.html) 판정 기준 코드 범례. services/llm.py의
# _build_system_prompt()가 내는 criterion_code enum(1-a/1-b/3/4/5/6/S-KLS/기타)과 값·순서를
# 그대로 맞춘다(드리프트 방지). CRITERION_LABELS는 삭제 제안 행 pill의 native title
# 한 줄(criterion_label)에도 같이 쓴다 — 팝오버(긴 설명, apps/dashboard/tooltips.py)와
# pill 툴팁(짧은 한 줄)은 분량만 다르고 뜻은 같아야 한다.
CRITERION_LABELS = {
    "1-a": "배경으로 스치듯 언급됨",
    "1-b": "AI가 부차 요소로만 곁들여짐",
    "3": "키워드 오탐",
    "4": "증시, 경제 브리핑 기사",
    "5": "AI 기업 단독 동향, 금융 연결 없음",
    "6": "묶음, 단신 브리핑 기사",
    "S-KLS": "KT, LG, SK 임시 스코프 제외",
}
# "기타"는 llm.py에 뜻이 정의돼 있지 않아 tooltip_key를 비워 둔다 — run_review.html이
# 그 항목을 통째로 건너뛴다(빈 팝오버 방지, 템플릿 상단 계약 "criterion_legend" 절).
CRITERION_LEGEND = [
    {"code": code, "tooltip_key": f"setting.run_review.criterion.{code}", "aria_label": f"판정 기준 {code}"}
    for code in CRITERION_LABELS
] + [{"code": "기타", "tooltip_key": "", "aria_label": "판정 기준 기타"}]

# SET-010 진행 표시(docs/planning.md "SET-010 진행 표시" 2번) — job_key별로 무엇을 세는지
# 다르다. 수집은 키워드 단위(전체 건수를 실행 전에 모른다), 판정은 기사 단위다. 통일하지
# 않고 낱말만 계약 키(progress_unit)로 내린다 — 최종 문구(어순 등)는 PD가
# _run_node.html에서 정한다. 여기 없는 job_key(아직 미구현, 또는 아래처럼 국면 표시로
# 확정된 job)는 빈 문자열로 떨어진다.
#
# 🔴 "newsroom_filter"(그리고 insight/weekly/monthly/newsroom_compose)는 여기
# 없다 — 배치 전체 1호출 job이라 건별 진행 간격이라는 개념이 없다(docs/planning.md
# 뉴스룸 12-2 (a) "배치 전체 1호출을 택한다").
#
# ⚠️ 2026-09-15 정정 — 이 자리에 있던 종전 문장은 틀렸다. "여기서 빼면
# _run_job_display()의 진행률(progress_current/progress_total)이 꺼진다"고
# 적혀 있었는데, 실제로 진행률을 그릴지 말지 가르는 키는 progress_unit이 아니라
# progress_total이었다(_run_node.html "{% elif job.progress_total %}") —
# progress_unit은 title(마우스 올림) 문구에만 쓰인다. 그래서 이 dict에서
# "newsroom_filter"를 뺐어도 target_count가 progress_total로 그대로 내려가
# "0/39"가 찍혔고, 사용자가 화면에서 직접 발견했다("시간초는 가는데 앞에있는
# 숫자가 안올라가"). 실제 조치는 _run_job_display()가 RESUME_FROM_SCRATCH_JOB_KEYS에
# 있는 job_key에는 progress_current/progress_total/progress_unit 셋 다 내리지
# 않는 것이다(그 함수의 "running" 분기 참고) — 이 dict는 이제 "1호출이 아닌
# job의 단위 낱말"만 담당하고, 1호출 job을 막는 실제 방어선이 아니다.
PROGRESS_UNIT_BY_JOB = {
    "collect": "키워드",
    "cleanup": "자료",
    "newsroom_collect": "키워드",
}

# 🔴 2026-09-17 신설(docs/design.md "SET-010 · 실행" 26차 개정 "① 1호출 단계의 진행
# 표시" ②-2) — RESUME_FROM_SCRATCH_JOB_KEYS(1호출 다섯)가 실행 중일 때 progress_note에
# 채우는 문장. 사용자 물음("3단계는 왜 실행하고 있어요 이것만 뜨는거야?")에 대한 답이
# "셀 수 있는 진행률이 없다"는 사실 자체다 — 그래서 "N/M" 대신 "무엇을 쥐고 있나"만
# 말한다. {count}에 RunJob.target_count를 끼운다. 낱말은 노드 이름과 맞춘다(②-2 표
# "24차 ③번이 '그룹화'에서 겪은 어긋남을 여기서 만들지 말 것").
PROGRESS_NOTE_TEMPLATE_BY_JOB = {
    "insight": "기사 {count}건을 한꺼번에 읽고 있어요",
    "weekly": "주요 이슈 {count}건을 보고서로 쓰고 있어요",
    "monthly": "주요 이슈 {count}건을 보고서로 쓰고 있어요",
    "newsroom_filter": "기사 {count}건을 한꺼번에 선별하고 있어요",
    "newsroom_compose": "기사 {count}건을 브리핑으로 쓰고 있어요",
}

# 중단 요약(state=='stopped')의 세 갈래(PD 확정, 2026-09-15) — "다시 누르면 어디서부터인가"가
# 단계마다 다르다. collect/newsroom_collect는 collector 중복 체크가 이미 받은 기사를
# 걸러 이어받고, cleanup은 제안이 이미 있는 기사가 다음 대상에서 빠져 남은 건부터
# 잇지만, insight/weekly/monthly(1호출 단계)는 중간이 없어 처음부터 다시 돈다 — 그
# 갈래엔 건수를 찍지 않는다("29건까지 했다"가 "29건은 남아 있겠지"로 오독된다).
#
# 🔴 "newsroom_filter"도 이 갈래다(2026-09-15 PE 추가, docs/planning.md 뉴스룸 12-5 PE
# 인계 3번) — 배치 전체 1호출이라 cleanup과 달리 중간이 없다. 종전 코드는 이 job을
# collect류(이어하기)로 취급해 "남은 기사부터 이어해요"라고 말했는데, 1호출에는 애초에
# "남은 기사"라는 게 없어 사실과 달랐다(같은 절 실측).
#
# 🔴 "newsroom_compose"도 같은 이유로 여기 들어간다(뉴스룸 정책 12-3 (a) "배치
# 전체 1호출") — 발송문도 배치 하나를 한 번에 조립하는 1호출이라 중간이 없다.
RESUME_FROM_SCRATCH_JOB_KEYS = ("insight", "weekly", "monthly", "newsroom_filter", "newsroom_compose")

# 🔴 2026-09-16 23차 개정(docs/planning.md 「SET-010 실행 중단」 1번) — 중단 버튼이
# 살아 있는 셋. 호출 단위가 건별(키워드 1개, 기사 1개)인 job만 멈출 자리가 있다 —
# 나머지 다섯은 배치 전체가 LLM 1호출이라 코드가 손댈 지점이 아예 없다(같은 문서
# "「멈출 자리 없음」은 「아직 안 만든 것」이 아니라 「만들 수 없는 것」이다").
STOPPABLE_JOB_KEYS = ("collect", "newsroom_collect", "cleanup")

# 🔴 반복 실패 자료 지목 문턱(docs/planning.md 「SET-010 검토 단위」 9번, design.md
# 23차 개정 ②-1). 1회는 정상 범위(실측 실패율 2.9%), 2회는 같은 시간대 rate limit
# 하나로 설명된다. 3회부터는 서로 다른 실행에 걸쳐 계속 실패한 것이라 원인이 그
# 자료 쪽으로 좁혀진다.
STUCK_FAIL_THRESHOLD = 3

# SET-010 검토 화면(run_review.html) "① 검토 대상"/"② AI가 한 일" 칸에 쓰는 낱말
# (docs/design.md 5차 개정 ⑦ PE 인계). cleanup만 실제 LLM 판정 배치를 갖고 있어
# 지금은 이 값만 채운다 — insight 등 미구현 job_key는 없으면 review.input/step이
# 그 칸을 채우지 않고 조용히 기존 빈 상태 문구로 떨어진다(템플릿이 이미 그렇게 짜여 있다).
# 🔴 2026-09-15 PE 신설 — "insight" 항목을 더했다(3단계 판정 데이터 층). summary 문구는
# run_review.html 상단 계약이 든 예시 그대로다.
# 🔴 같은 날 뒤이은 라운드 — "weekly"·"monthly"를 더한다(4, 5단계).
REVIEW_INPUT_LABEL_BY_JOB = {
    "cleanup": "미검증 뉴스", "insight": "검증된 뉴스",
    "weekly": "이번 주 이슈", "monthly": "지난달 이슈",
}
REVIEW_STEP_SUMMARY_BY_JOB = {
    "cleanup": "기사마다 관련성을 판정했어요",
    # 🔴 2026-09-17 낱말 통일 — "묶었어요"를 "그룹화했어요"로 바꿨다(24차 ③번
    # 설명문이 이미 "그룹화"를 쓰는데 이 화면만 "묶다"로 남아 같은 일을 세
    # 낱말로 부르고 있었다. 아래 ZERO_TARGET_SUMMARY_BY_JOB·
    # _insight_block_reason()·_insight_backlog()·_insight_flow()도 같은 라운드에
    # 함께 바꿨다 — 하나만 고치면 낱말이 공존해 더 나빠진다).
    "insight": "같은 사건을 이슈로 그룹화했어요",
    "weekly": "이슈를 모아 주간 보고서를 썼어요", "monthly": "이슈를 모아 월간 보고서를 썼어요",
}

# 🔴 2026-09-15 2라운드 PE 신설 — _run_job_display()의 "대상 0건" 교착 방지 분기(아래)가
# 쓰는 job_key별 요약 문구. GATED_JOB_KEYS 두 job의 "대상"이 서로 다른 말이라(cleanup은
# 미검증 뉴스, insight는 이슈로 묶을 뉴스) 문구도 갈라야 한다 — 하나로 고정해 두면
# insight가 대상 0건으로 끝났을 때 "정리할 미검증 뉴스가 없었어요"라는, insight와
# 무관한(cleanup 전용) 문장이 그대로 찍힌다. 실제로 인위 RunJob(job_key="insight",
# target_count=0)으로 재현해 확인한 문제다(트랜잭션 롤백 검증, 커밋하지 않음).
ZERO_TARGET_SUMMARY_BY_JOB = {
    "cleanup": "정리할 미검증 뉴스가 없었어요",
    # 🔴 2026-09-17 낱말 통일 — "묶을"을 "그룹화할"로 바꿨다(REVIEW_STEP_SUMMARY_BY_JOB
    # 주석 참고, 다섯 자리를 한 라운드에 함께 바꾼 것 중 하나).
    "insight": "이슈로 그룹화할 뉴스가 없었어요",
    # 🔴 같은 날 뒤이은 라운드 — 없으면 cleanup 전용 문구("정리할 미검증 뉴스가
    # 없었어요")가 그대로 찍혀 4, 5단계와 무관한 문장이 뜬다.
    "weekly": "이번 주에 만들어진 이슈가 없었어요",
    "monthly": "지난달에 만들어진 이슈가 없었어요",
    # 🔴 뉴스룸 3단계(2026-09-15 PE 추가) — 통과 기사가 0건이어도 실행이 실패한 게
    # 아니다. LLM을 부르지 않고 코드가 고정 문구("오늘은 새로운 소식이 없습니다.")로
    # NewsroomMessage를 만들고 정상 완료된다(정책 12-3 (a)) — 그 사실을 요약이
    # 말해 줘야 "0건인데 왜 완료라고 하지"로 읽히지 않는다.
    "newsroom_compose": "통과한 기사가 없어 고정 문구로 만들었어요",
}

# 🔴 2026-09-15 PE 신설 — review.step.model이 종전에는 settings.ANTHROPIC_MODEL_FAST로
# 고정돼 있었다(3~5단계 설계 인계 "job_key로 갈라야 한다"). cleanup은 실제로
# services/llm.py classify_news()가 settings.BEDROCK_MODEL_FAST를 쓰고 그 친숙한 이름이
# ANTHROPIC_MODEL_FAST다. insight(및 나중의 weekly/monthly)는 generate_insights()가
# settings.BEDROCK_MODEL_SMART를 쓴다 — 🔴 그 값을 그대로 보여준다. 친숙한 이름
# ANTHROPIC_MODEL_SMART("claude-sonnet-5")를 대신 보여주면, BEDROCK_MODEL_SMART가 지금
# 비용 때문에 Haiku를 가리키고 있는데(config/settings/base.py) 화면은 Sonnet이 돌았다고
# 말하는 거짓 표시가 된다. 문자열이 길어도(예: "global.anthropic.claude-haiku-...")
# 템플릿이 자르지 않기로 이미 정해져 있다(run_review.html 상단 계약).
REVIEW_MODEL_KEY_BY_JOB = {"insight": "BEDROCK_MODEL_SMART", "weekly": "BEDROCK_MODEL_SMART", "monthly": "BEDROCK_MODEL_SMART"}


# SET-010 노드 배지 어휘(docs/planning.md "SET-010 노드 배지" 절, 2026-09-15 확정) —
# done과 idle이 사라지고 여섯 값(running/review/todo/clear/failed/stopped)으로
# 바뀐다. 낱말은 PD 몫이라 새로 짓지 않는다 — templates/setting/_run_node.html
# "🔴 ③ 낱말은 해요체다" 절이 이미 같은 라운드에 이 여섯 낱말을 확정해 둔 것을
# 그대로 옮긴다(값 이름을 바꾸면 그 템플릿의 data-state 분기가 깨진다).
STATE_LABELS = {
    "running": "실행 중",
    "review": "검토 필요",
    "todo": "실행 가능",
    "clear": "실행 대상 없음",
    "failed": "실행 실패",
    "stopped": "실행 중단",
}

# clear(할 일 없음)면 버튼도 잠근다(사용자 결정, 2026-09-16, 실측 버그 신고) — 배지와
# 버튼이 항상 같은 말을 해야 한다. "1단계를 안 했는데 2·3단계가 열린다"도 이 규칙
# 하나로 함께 풀린다(조사 2·3단계가 이미 clear인데 버튼만 열려 있었을 뿐이었다).
#
# 🔴 아래 세 문구는 PE가 이 파일의 기존 block_reason 문구 패턴(예:
# _insight_block_reason()의 "이슈로 묶을 뉴스가 없어요")을 흉내 내 임시로 지은
# 것이었다. 🔴 2026-09-16 PD 확정 문구로 교체했다(docs/design.md 14차 개정).
#
# 🔴 셋이 한 형태다 — 앞 문장은 왜 지금 잠겼는가, 뒤 문장은 무엇을 하면 열리는가.
#    툴팁은 마우스를 올려야 보이는 자리라, 올린 사람이 두 번째 문장까지 읽고
#    다음 행동을 고를 수 있어야 한다. 한 문장만 두면 배지 낱말("실행 대상 없음")과
#    같은 말을 두 번 하게 된다.
# 🔴 3단계가 2단계가 아니라 1단계까지 가리키는 이유 — 이 문구가 뜨는 때는 미검증
#    뉴스가 0건인 때다(있으면 _insight_block_reason()의 "아직 정리되지 않은 뉴스가
#    N건 있어요"가 먼저 걸린다). 즉 2단계도 같이 잠겨 있어서 실제로 누를 수 있는
#    첫 버튼은 1단계 수집이다. 누를 수 없는 버튼을 가리키는 안내문은 잠긴 버튼을
#    하나 더 만드는 것과 같다.
# ⚠️ 문자열에 줄바꿈을 넣지 말 것 — title 속성에서 브라우저마다 다르게 접힌다.
CLEANUP_CLEAR_BLOCK_REASON = (
    "정리할 미검증 뉴스가 없어요. 1단계 수집으로 새 기사가 들어오면 열려요"
)
# 🔴 2026-09-16 "SET-010 검토 단위" 절 확정 — INSIGHT_CLEAR_BLOCK_REASON을
# 없앴다. 3단계 대상이 "직전 확정 이후 새로 검증된 것"(증분형)에서 "탈락 표식
# 없는 미배정 전체"로 바뀌면서 _insight_block_reason()이 이제 clear일 때 항상
# 스스로 구체적인 사유("아직 정리되지 않은 뉴스가 있어요"/"이슈로 묶을 뉴스가
# 없어요")를 채운다 — 이 상수가 채우던 "잔여는 있지만 새 재료가 없는" 중간
# 상태 자체가 새 설계에는 없다.
NEWSROOM_COMPOSE_CLEAR_BLOCK_REASON = (
    "마지막 브리핑과 재료가 같아서 지금 만들면 같은 글이 또 나와요. "
    "1단계 수집과 2단계 기사 선별로 새 기사가 통과하면 열려요"
)


def _clear_can_run(job: dict, clear_block_reason: str) -> bool:
    """state=='clear'(할 일 없음)면 can_run을 강제로 False로 내리고, job에
    block_reason이 아직 없으면(빈 문자열/키 없음) clear_block_reason으로 채운다.
    이미 더 구체적인 block_reason이 채워져 있으면(예: 선행 단계 미완 사유)
    그대로 둔다 — 이 함수는 "그 밖에는 다 채웠는데 clear인데 이유가 없는" 틈만
    메운다. 반환값이 곧 can_run이다."""
    if job["state"] == "clear":
        if not job.get("block_reason"):
            job["block_reason"] = clear_block_reason
        return False
    return True


def _today_local():
    """오늘 날짜(로컬 타임존). SET-010 노드 배지의 날짜 축 판정과 사고 배지("오늘
    벌어진 실패·중단")의 하루 경계가 전부 이 함수를 쓴다(docs/planning.md "SET-010
    노드 배지" 8-6 "하루 경계는 로컬 날짜로 판정한다", USE_TZ=True에서 aware
    datetime을 직접 .date()하지 않는 이유는 CLAUDE.md 패턴 12)."""
    return timezone.localtime(timezone.now()).date()


def _is_today_local(dt) -> bool:
    """dt(aware datetime)의 로컬 날짜가 오늘인지. dt가 None이면 False다 — 아직 한
    번도 안 찍힌 시각을 "오늘"로 오판하지 않는다."""
    return dt is not None and timezone.localtime(dt).date() == _today_local()


def _job_run_state(run_job, job_key, has_work):
    """RunJob.status와 "할 일이 있나" 축 판정(has_work)을 화면 어휘
    (running/review/todo/clear/failed/stopped)로 바꾼다. _run_job_display()(노드
    그래프)와 검토 화면 머리글(_run_review_context())이 이 함수를 함께 써서, 같은
    상태를 두 화면이 다른 말로 부르는 것을 막는다.

    🔴 2026-09-15 개정(docs/planning.md "SET-010 노드 배지") — "무엇을 했는가"
    (RunJob.status 그대로)에서 "지금 눌러야 할 일이 있는가"로 축을 바꿨다. done과
    idle은 더 이상 반환하지 않는다 — done 안에 눌려 담겨 있던 완료/확정됨/취소됨
    셋의 할 일 여부가 서로 달라서다(같은 문서 8-1).

    판정 순서가 뜻을 가진다 — 먼저 걸리는 것이 배지를 차지한다.
      1. 실행 중
      2. 검토 대기 — 휴먼 인 더 루프가 사람을 기다리는 자리다. "할 일 있음"의
         한 종류라 todo와 같은 색을 쓰지만(_run_node.html), 이름은 갈라 둔다.
      3. 🔴 오늘 벌어진 실패 또는 중단 — 날짜가 바뀌면 이 자리를 잃고 4번으로
         떨어진다("어제 실패가 오늘 빨간 배지로 남으면 안 된다").
      4. 그 밖 전부 — has_work 축 판정(todo/clear). 확정됨·취소됨과, 오늘이 아닌
         실패·중단도 전부 여기로 떨어진다(같은 문서 "확정됨과 취소됨은 이 순서에
         자리를 갖지 않는다. 4번으로 떨어진다")."""
    if run_job.status == RunJob.STATUS_RUNNING:
        return "running", STATE_LABELS["running"]
    if job_key == "cleanup":
        # 🔴 2026-09-16 "SET-010 검토 단위" 절 확정(PD 19차 개정) — cleanup은
        # RunJob.status를 더 이상 보지 않는다. A/B 두 수만 본다 — 성공도 실패도
        # 중단도 전부 A 또는 B로 흡수되므로 이 job_key에는 failed/stopped 배지가
        # 따로 존재하지 않는다(상태가 셋뿐이다: todo/review/clear).
        from services.runner import cleanup_ab_split
        a_qs, b_qs = cleanup_ab_split()
        if b_qs.exists():
            return "todo", STATE_LABELS["todo"]
        if a_qs.exists():
            return "review", STATE_LABELS["review"]
        return "clear", STATE_LABELS["clear"]
    if job_key in GATED_JOB_KEYS and run_job.status == RunJob.STATUS_DONE and run_job.target_count > 0:
        return "review", STATE_LABELS["review"]
    if run_job.status == RunJob.STATUS_FAILED and _is_today_local(run_job.finished_at):
        return "failed", STATE_LABELS["failed"]
    # 🔴 2026-09-16 23차 개정(docs/planning.md 「SET-010 실행 중단」 2번 마지막 문단) —
    # 「중단 요청 시각이 비어 있을 것」을 더한다. 사람이 일부러 멈춘 것을 사고 배지로
    # 칠하면 "무슨 일이 났지"를 찾게 된다 — 사람이 멈춘 중단은 여기서 걸리지 않고
    # 아래 4번(재료 유무 판정)으로 떨어져 평상시 배지를 받는다.
    if (
        run_job.status == RunJob.STATUS_STOPPED
        and _is_today_local(run_job.finished_at or run_job.heartbeat_at)
        and not run_job.stop_requested_at
    ):
        return "stopped", STATE_LABELS["stopped"]
    return ("todo", STATE_LABELS["todo"]) if has_work else ("clear", STATE_LABELS["clear"])


def _today_or_past(dt):
    """15차 개정 ⑥-2, 13차 ①번 서식, 22차 개정 ⑤번(어순 변경) — 요약 줄 접두
    `{오늘|지난} {시각|날짜} {사건}`의 앞 두 조각을 만든다. dt가 오늘(로컬 날짜)이면
    ("오늘", "HH:MM")을, 아니면
    ("지난", "MM/DD")를 반환한다 — "지난" 쪽에 시각을 적지 않는 것은 지난 일에서
    사람이 쓰는 정보가 몇 시냐가 아니라 며칠 전이냐이기 때문이다(13차 ④번 근거)."""
    if _is_today_local(dt):
        return "오늘", f"{timezone.localtime(dt):%H:%M}"
    return "지난", f"{timezone.localtime(dt):%m/%d}"


def _collect_article_count(run_job) -> int:
    """15차 개정 ⑦ PE 인계 핵심 — collect.summary가 세는 값은 새로 저장된 기사 수
    (`CollectionLog.collected_count` 합)이지 `RunJob.processed_count`(키워드 수, 실측
    19건 고정)가 아니다. RunJob과 CollectionLog는 FK로 이어져 있지 않다 —
    services/collector.py의 run_collection()이 이 실행 도중 정확히 1건을 남기므로
    (진행중 RunJob은 전역에 최대 1개라 RunJob.Meta.constraints가 겹침을 막는다),
    그 실행 구간([started_at, finished_at])에 든 CollectionLog를 그 실행의 것으로
    본다. Sum으로 합치는 이유는 향후 실행 하나가 로그를 여러 건 남기게 되어도
    이 함수가 그대로 맞기 위해서다(지금은 항상 1건)."""
    qs = CollectionLog.objects.filter(started_at__gte=run_job.started_at)
    if run_job.finished_at:
        qs = qs.filter(started_at__lte=run_job.finished_at)
    return qs.aggregate(total=Sum("collected_count"))["total"] or 0


def _newsroom_collect_article_count(run_job) -> int:
    """newsroom_collect.summary가 세는 값 — 그 실행 구간에 채널에 새로 들어온 기사 수
    (`NewsroomArticle.collected_at` 기준, 위 _collect_article_count()와 같은 이유로
    processed_count(키워드 수)를 쓰지 않는다). RunJob이 newsroom_id를 저장하지
    않으므로(services/runner.py의 kwargs는 스레드 인자로만 쓰이고 영속되지 않는다)
    지금 유일하게 고를 수 있는 대상 채널(_target_newsroom(), 활성 채널이 정확히
    1개일 때만 정해진다)을 그대로 쓴다 — 이 축의 다른 모든 표시도 이미 같은
    전제(활성 채널 1개) 위에 서 있다."""
    room = _target_newsroom()
    if not room:
        return 0
    qs = room.articles.filter(collected_at__gte=run_job.started_at)
    if run_job.finished_at:
        qs = qs.filter(collected_at__lte=run_job.finished_at)
    return qs.count()


# CONFIRMED 요약 줄의 단위 낱말(15차 개정 ⑥-1). weekly/monthly는 이 규약의 대상이
# 아니다(⑥-2 각주) — CONFIRMED로 떨어져도 _weekly_job_context()/_monthly_job_context()가
# todo/clear 상태에서 항상 summary_override로 덮어써 여기 값이 화면에 노출되지 않는다.
CONFIRMED_UNIT_BY_JOB = {"cleanup": "기사", "insight": "주요 이슈"}


def _confirmed_count(run_job, job_key) -> int:
    """CONFIRMED 요약 줄의 건수. 🔴 insight는 `processed_count`를 쓰지 않는다 —
    그 값은 _run_insight()가 "이슈로 묶을 후보로 고려한 뉴스 수"(len(targets))로
    채운 것이라 "그 실행이 만든 이슈 수"와 다른 수다(예: 뉴스 71건을 고려해 이슈
    6건을 만들 수 있다). 실제로 확정(채택)된 Insight 개수는 그 배치가 남긴
    RunDraft에서 직접 센다 — _confirm_insight_drafts()가 채택된 초안마다
    RunProposal.STATUS_ACCEPTED로 남긴다.

    cleanup은 processed_count 자체가 이미 "판정한 기사 수"라 그대로 쓴다(생성
    시점에 성공+실패를 합쳐 저장한다, _run_cleanup() 참고) — design.md 15차 개정
    ⑦번이 "수는 이미 맞다"고 확인한 자리다."""
    if job_key == "insight":
        return RunDraft.objects.filter(
            run_job=run_job, draft_type=RunDraft.TYPE_INSIGHT, status=RunProposal.STATUS_ACCEPTED,
        ).count()
    return run_job.processed_count


def _pending_review_run_jobs(job_key):
    """job_key에 걸쳐 확정 대기 제안(또는 초안)이 남아 있는 RunJob 전부,
    started_at 오름차순(오래된 배치가 먼저). 검토 화면·확정·취소·노드 배지가
    이 목록 하나를 같이 봐서 「가장 최근 RunJob 하나」에만 묶이던 문제를
    없앤다(docs/planning.md "SET-010 검토 단위" 절, 2026-09-16 확정 — 사용자가
    배치별로 나눠 보여주던 것을 기각하고 "확정을 기다리는 것 전부"를 보여주라고
    확정했다). 실측 사고 — 같은 날 cleanup을 네 번 돌려 제안이 pk107(153건)·
    pk108(21건)·pk130(161건)·pk131(5건)로 쌓였는데, 종전 코드는 가장 최근
    RunJob(pk131) 하나만 봐서 앞 세 배치의 제안 335건이 화면에서 사라졌다.

    RunDraft 기반 job(insight/weekly/monthly)은 RunDraft를, 그 외(cleanup 등)는
    RunProposal을 본다. RUNNING인 배치는 제외한다 — services/runner.py가 건별로
    그때그때 제안을 저장하므로 진행 중인 배치도 이미 대기 제안을 갖지만, 아직
    끝나지 않은 배치를 확정·취소 대상에 섞으면 안 된다(그 배치는 아직 더 늘어날
    수 있다)."""
    model = RunDraft if job_key in ("insight", "weekly", "monthly") else RunProposal
    pending_job_ids = model.objects.filter(
        run_job__job_key=job_key, status=RunProposal.STATUS_PENDING,
    ).values_list("run_job_id", flat=True).distinct()
    return list(
        RunJob.objects.filter(pk__in=pending_job_ids)
        .exclude(status=RunJob.STATUS_RUNNING)
        .order_by("started_at", "pk")
    )


def _representative_run_job(job_key):
    """_run_job_display()(노드 그래프)와 _run_review_context()(검토 화면
    머리글)가 "이 job_key의 RunJob"으로 취급할 대표 하나. 진행 중이거나(또는
    한 번도 실행한 적이 없으면) 그냥 가장 최근 RunJob을 쓰고, 그렇지 않으면
    확정 대기 제안이 남아 있는 배치 중 가장 최근 것을 우선한다 — 없으면 가장
    최근 RunJob 그대로다.

    이 함수가 없으면 "가장 최근 RunJob"만 본다. 확정 대기 제안이 있는 배치
    뒤에 대상 0건 등으로 새 RunJob이 하나 더 생기면(예: pk131) 그 최근 배치가
    이전 배치(pk130)를 노드 배지와 검토 화면 양쪽에서 가려 버린다.

    🔴 cleanup은 이 함수를 상태 판정에 쓰지 않는다(위 _job_run_state()가 A/B로
    직접 판정한다) — 다만 요약 줄(지난 실행 기록)에는 여전히 이 함수가 고른
    run_job을 쓴다."""
    latest = RunJob.objects.filter(job_key=job_key).order_by("-started_at", "-pk").first()
    if latest is None or latest.status == RunJob.STATUS_RUNNING:
        return latest
    pending_jobs = _pending_review_run_jobs(job_key)
    if pending_jobs:
        return pending_jobs[-1]
    # 🔴 확정 이력은 시작 순서와 어긋날 수 있다 — 여러 배치를 한 번에 확정하면
    # (위 setting_run_review_confirm()) started_at이 더 이른 배치가 더 나중에
    # 시작된 배치보다 나중에 확정될 수 있다. "마지막 확정"을 말하는 요약 줄이
    # 실제로 가장 최근에 확정된 배치를 가리키도록, confirmed_at 기준으로도 한 번
    # 더 비교한다.
    latest_confirmed = (
        RunJob.objects.filter(job_key=job_key, status=RunJob.STATUS_CONFIRMED, confirmed_at__isnull=False)
        .order_by("-confirmed_at", "-pk").first()
    )
    if not latest_confirmed:
        return latest
    latest_event = latest.finished_at or latest.started_at
    if latest_event and latest_event > latest_confirmed.confirmed_at:
        return latest
    return latest_confirmed


# 🔴 2026-09-17 신설(docs/design.md 26차 개정 "①-3 예상 시간을 말하지 않는다.
# 지난 실행의 기록만 말한다") — 1호출 다섯(RESUME_FROM_SCRATCH_JOB_KEYS) 실행 중
# 화면의 보조 줄. 초 단위 정밀 기록(_format_duration())을 재사용하지 않는다 —
# 그 함수는 검토 화면·로그가 쓰는 "지나간 배치의 정밀한 기록"이고, 여기는 "실행
# 중" 화면이라 사용자 지시("실행 시 초는 노출하지마")의 문면에 걸린다.
def _last_run_duration_note(job_key: str) -> str:
    """같은 job_key의 가장 최근 "성공한"(완료 또는 확정됨) 실행 소요 시간을 분
    단위 문자열로 반환한다. 이력이 없으면 빈 문자열 — 호출부가 그러면 키 자체를
    내리지 않는다."""
    last = (
        RunJob.objects.filter(
            job_key=job_key, status__in=(RunJob.STATUS_DONE, RunJob.STATUS_CONFIRMED),
            started_at__isnull=False, finished_at__isnull=False,
        )
        .order_by("-finished_at", "-pk").first()
    )
    if not last:
        return ""
    seconds = (last.finished_at - last.started_at).total_seconds()
    if seconds < 60:
        return "1분 안쪽"
    return f"약 {round(seconds / 60)}분"


def _run_job_display(job_key, has_work):
    """job_key의 최신 RunJob과 "할 일이 있나" 축 판정(has_work)으로 노드
    표시값(state/state_label/summary/elapsed)을 만든다. 그 job_key로 RunJob이 한
    번도 없었으면 None을 반환한다 — 호출부가 has_work만으로 todo/clear를 채운다.

    상태 어휘는 _job_run_state()가 정한다 — templates/setting/_run_node.html이 아는
    값(running/review/todo/clear/failed/stopped)만 나온다.

    🔴 2026-09-15 개정(docs/planning.md "SET-010 노드 배지") — has_work 인자가
    늘고, done/idle이 사라졌다. 아래 함수 끝부분(state가 todo/clear로 떨어졌을 때)이
    RunJob.status를 직접 봐서 요약 문구를 만든다 — 완료/확정됨/취소됨/(오늘이
    아닌) 실패·중단이 전부 여기로 모인다."""
    run_job = _representative_run_job(job_key)
    if not run_job:
        return None
    state, state_label = _job_run_state(run_job, job_key, has_work)
    if state == "running":
        seconds = int((timezone.now() - run_job.started_at).total_seconds())
        # 🔴 2026-09-15 10차 개정 — "21초째"에서 "21초"로("째" 접미사 제거).
        # nn/nn (시간) 형태로 괄호 안에 들어가는 자리라 "21초째"로 두면 "0/10
        # (21초째)"처럼 문장이 아닌 자리에 문장형 접미사가 남는다
        # (_run_node.html "⚠️ elapsed 문자열이 '21초째'에서 '21초'로 바뀌어야
        # 괄호 안이 말이 된다" 계약).
        elapsed = f"{seconds // 60}분 {seconds % 60}초" if seconds >= 60 else f"{seconds}초"
        display = {
            "state": state, "state_label": state_label, "summary": "", "elapsed": elapsed,
        }
        # 🔴 2026-09-15 PE 수정(사용자가 화면에서 직접 발견 — newsroom_filter가
        # "0/39 (9초)"를 보였다. "시간초는 가는데 앞에있는 숫자가 안올라가").
        #
        # 🔴 종전 진단이 틀렸다 — 위 PROGRESS_UNIT_BY_JOB 정의 주석은 "newsroom_filter를
        # 거기서 빼면 진행률(progress_current/progress_total)이 꺼진다"고 적고
        # 있었는데 사실이 아니다. _run_node.html이 국면 표시(progress_note)와
        # 건수 표시(progress_current/progress_total) 중 무엇을 그릴지 가르는 키는
        # progress_total이지 progress_unit이 아니다(그 템플릿 181행
        # "{% elif job.progress_total %}") — progress_unit은 title(마우스 올림)
        # 문구에만 쓰인다. 그래서 progress_unit을 빼도 target_count(예: 39)가
        # progress_total로 그대로 내려가 "0/39"가 그대로 찍혔다.
        #
        # 🔴 진짜 조치 — 배치 전체 1호출 job에는 progress_current/progress_total/
        # progress_unit 셋 다 아예 내리지 않는다. 그러면 템플릿 181행의 elif가
        # 거짓이 되어 "else" 분기(job.elapsed만 표시)로 떨어진다. 이 job들은
        # 호출 하나가 끝날 때까지 processed_count가 0에 머물러 있어 "숫자가
        # 안 올라가는" 게 아니라 "숫자 자체가 의미가 없다"가 맞다 — 사용자가
        # 고른 해법("거짓말만 걷어내기")대로 숫자를 아예 안 보인다.
        #
        # 🔴 판정 기준은 RESUME_FROM_SCRATCH_JOB_KEYS를 그대로 재사용한다(새 목록을
        # 만들지 않는다) — "배치 전체 1호출이라 중간이 없다"가 그 목록과 이 조건이
        # 서 있는 같은 사실이다. 목록을 두 벌로 쪼개면 1호출 job이 새로 늘 때
        # 한쪽만 고쳐서 이 버그가 되살아난다(실제로 이번 사고가 그 유형이었다 —
        # PROGRESS_UNIT_BY_JOB이라는 별도 목록을 만들었다가 갱신을 깜빡했다).
        if job_key not in RESUME_FROM_SCRATCH_JOB_KEYS:
            # 🔴 분자는 처리를 마친 수(성공+실패)다(docs/planning.md "SET-010 진행
            # 표시" 5-(a)) — processed_count만 쓰면 실패가 섞인 배치가 목표
            # 건수(target_count)에 끝내 못 닿은 채 완료돼, "71건 중 68건"에서
            # 멈춘 것처럼 보인다. DB 필드(processed_count)의 뜻 자체는 바꾸지
            # 않는다 — 검토 화면과 로그가 그 뜻으로 읽는다. 여기서 합치는 건
            # 화면에 내리는 값뿐이다.
            display["progress_current"] = run_job.processed_count + run_job.failed_count
            display["progress_total"] = run_job.target_count
            display["progress_unit"] = PROGRESS_UNIT_BY_JOB.get(job_key, "")
        else:
            # 🔴 2026-09-17 신설(docs/design.md 26차 개정 "① 1호출 단계의 진행 표시",
            # 사용자 물음 "3단계는 왜 실행하고 있어요 이것만 뜨는거야? 진행 현황
            # 안보여줘?") — 1호출 다섯은 셀 수 있는 진행률이 없다(호출이 끝나야
            # 안이 보인다). 말할 수 있는 것은 "무엇을 쥐고 있나"뿐이라 문장으로
            # 채운다. target_count가 아직 0이면(RunJob이 막 만들어져 대상을 세기
            # 전 구간) 이 문장을 만들지 않는다 — "기사 0건을 한꺼번에 읽고
            # 있어요"는 거짓이다(②-5). 그때는 _run_node.html이 기존 셋째 갈래
            # ("실행하고 있어요")로 떨어진다.
            if run_job.target_count:
                template = PROGRESS_NOTE_TEMPLATE_BY_JOB.get(job_key)
                if template:
                    display["progress_note"] = template.format(count=run_job.target_count)
            last_duration = _last_run_duration_note(job_key)
            if last_duration:
                # 🔴 ②-3 — 예측이 아니라 지난 성공 실행의 기록이다. 이력이 없으면
                # (첫 실행) 키 자체를 안 내린다 — 그 줄만 사라진다.
                display["last_duration"] = last_duration
        if run_job.failed_count:
            display["progress_failed"] = run_job.failed_count
        # 🔴 2026-09-16 23차 개정(docs/planning.md 「SET-010 실행 중단」 9-7) —
        # stop_url은 STOPPABLE_JOB_KEYS 셋에만 내린다. 나머지 다섯은 stop_url이
        # 없어 _run_button.html이 잠긴 중단 버튼(기본 문구)으로 그린다.
        if job_key in STOPPABLE_JOB_KEYS:
            display["stop_url"] = reverse("setting_run_stop", args=[job_key])
            display["stopping"] = bool(run_job.stop_requested_at)
        return display
    if state == "stopped":
        # 🔴 세 갈래(PD 확정, 2026-09-15) — "다시 누르면 어디서부터인가"에 답한다.
        # 빗금 표기(종전 "29/71건")를 걷고 위 진행 줄과 같은 어순("N건 중 M건")으로
        # 맞춘다 — 실행 중에 보던 표기와 3초 뒤 멈췄을 때 표기가 다르면 같은 수인지
        # 확인하는 데 시간이 든다.
        current = run_job.processed_count + run_job.failed_count  # 위 running과 같은 이유로 실패 건도 더한다.
        if job_key in RESUME_FROM_SCRATCH_JOB_KEYS:
            # 🔴 건수를 찍지 않는다 — 처음부터 다시 돌아서 "어디까지 했는지"가 다시
            # 누르는 판단에 아무 도움이 되지 않는다. 건수를 보이면 "그만큼은 남아
            # 있겠지"로 오독된다(사실과 반대).
            summary = "중간에 멈췄어요. 다시 누르면 처음부터 실행해요"
        elif job_key in ("collect", "newsroom_collect"):
            summary = (
                f"{PROGRESS_UNIT_BY_JOB.get(job_key, '')} {run_job.target_count}건 중 {current}건까지 "
                "수집하고 멈췄어요. 다시 누르면 이어서 해요"
            )
        else:
            # cleanup — 건별 판정이라 이어하기가 성립하는 유일한 남은 job_key다.
            # newsroom_filter는 2026-09-15에 위 RESUME_FROM_SCRATCH_JOB_KEYS로 옮겨졌다
            # (1호출이라 여기 닿지 않는다).
            summary = (
                f"{PROGRESS_UNIT_BY_JOB.get(job_key, '')} {run_job.target_count}건 중 {current}건까지 "
                "판정하고 멈췄어요. 남은 자료부터 이어해요"
            )
        return {"state": state, "state_label": state_label, "summary": summary}
    if state == "failed":
        # 🔴 여기 닿는 것은 "오늘 벌어진" 실패뿐이다(_job_run_state 우선순위 3번) —
        # 어제 이전 실패는 이미 todo/clear로 내려가 아래 마지막 블록에서 요약된다.
        return {"state": state, "state_label": state_label, "summary": "실행이 실패했어요"}
    if state == "review":
        if job_key == "cleanup":
            # 🔴 2026-09-16 PD 19차 개정 — 완료형을 금지한다. "N건 판정을
            # 마쳤어요"는 B가 0이라는 사실("다 됐다")을 말하는 문장인데, 이제
            # 그 정보는 적체 줄(job.backlog, "판정 A/(A+B)")이 전담한다. 이
            # 줄은 지나간 실행의 기록만 짧게 남긴다 — 대표 배치(가장 최근
            # 확정 대기 배치)의 처리 시각과 건수.
            prefix, when = _today_or_past(run_job.finished_at)
            summary = f"{prefix} {when} 판정, {run_job.processed_count}건"
        elif run_job.failed_count:
            # 🔴 2026-09-16 18차 개정 — insight/weekly/monthly는 여전히 배치
            # 하나가 review를 통째로 정하므로(대상 전량에 실패가 섞여도 B라는
            # 개념이 없다) 실패가 있으면 그 사실을 여기서 말한다.
            summary = (
                f"{run_job.target_count}건 중 {run_job.processed_count}건 판정, "
                f"실패 {run_job.failed_count}건"
            )
        else:
            summary = f"{run_job.processed_count}건 판정을 마쳤어요, 검토를 기다리고 있어요"
        return {"state": state, "state_label": state_label, "summary": summary}

    # 🔴 여기부터는 state가 "todo" 또는 "clear"다(docs/planning.md "SET-010 노드
    # 배지" 4번 "확정됨과 취소됨은 4번으로 떨어진다", 3번 "사고 사실은 요약 줄에
    # 남긴다"). run_job.status는 DONE(비게이트 또는 대상 0건)/CONFIRMED/CANCELED,
    # 또는 오늘이 아닌 FAILED/STOPPED 중 하나다 — 배지 색은 이미 todo/clear로
    # 정해졌으니, 요약 줄만 실제 status를 보고 사실대로 말한다.
    if run_job.status == RunJob.STATUS_FAILED:
        # 🔴 template run.html 상단 계약(13차 개정 ③) — "지난 실패 MM/DD"(사건만,
        # 건수 없음). 오늘 난 실패는 여기 닿지 않는다(_job_run_state()가 이미
        # 앞에서 "실행이 실패했어요"로 가로챈다) — 그래서 여기 오는 finished_at은
        # 항상 오늘이 아니지만, 판정은 다른 곳과 같은 _today_or_past()로 통일한다.
        #
        # 🔴 2026-09-16 PE 수정 — cleanup은 이제 이 분기에 "오늘" 실패도 닿을 수
        # 있다(위 _job_run_state()가 cleanup의 failed(오늘) 우선순위 자체를 없앴다
        # — 실패는 전부 B로 흡수돼 배지는 todo/review/clear 셋뿐이다). 그런데 이
        # 코드는 prefix를 버리고 "지난"을 하드코딩하고 있었다 — 다른 job_key는
        # 이 분기에 항상 지난 실패만 왔으니(오늘 실패는 早 위 "state==failed"
        # 분기가 가로챈다) 드러나지 않던 버그다. 실제 prefix를 쓴다.
        prefix, when = _today_or_past(run_job.finished_at)
        summary = f"{prefix} {when} 실패"
    elif run_job.status == RunJob.STATUS_STOPPED:
        # 🔴 같은 이유로 prefix를 실제 값으로 쓴다("오늘 중단 13:05, 29건까지" —
        # PD 19차 개정 backlog 예시와 짝을 이루는 문구). 1호출 job
        # (RESUME_FROM_SCRATCH_JOB_KEYS)은 건수를 찍지 않는다 — "오늘" 중단 요약
        # (위 `if state == "stopped":` 분기)과 같은 이유다("그만큼은 남아
        # 있겠지"로 오독된다).
        stopped_at = run_job.finished_at or run_job.heartbeat_at
        if not stopped_at:
            summary = "중단된 적이 있어요"
        else:
            prefix, when = _today_or_past(stopped_at)
            # 🔴 2026-09-16 23차 개정(docs/planning.md 「SET-010 실행 중단」 9-7) —
            # 「사람이 멈춤」과 「끊겨서 멈춤」을 가르는 꼬리. 앞부분(22차 어순)은
            # 한 글자도 안 건드린다 — 아홉 노드가 한 벌이라 하나만 다른 서식이
            # 되면 그 줄만 튄다. RESUME_FROM_SCRATCH_JOB_KEYS는 애초에 중단 버튼이
            # 없어 stop_requested_at이 항상 비어 있으므로 tail도 항상 빈다.
            tail = " 하고 멈췄어요" if run_job.stop_requested_at else ""
            if job_key in RESUME_FROM_SCRATCH_JOB_KEYS:
                summary = f"{prefix} {when} 중단{tail}"
            else:
                current = run_job.processed_count + run_job.failed_count
                summary = f"{prefix} {when} 중단, {current}건까지{tail}"
    elif run_job.status == RunJob.STATUS_CONFIRMED:
        # 🔴 15차 개정 ⑥-2 — "마지막 확정 MM/DD HH:MM"(13차가 쓰지 말라고 못박은
        # 종전 서식)에서 {오늘|지난} 접두로 바꾸고, 건수에 단위 낱말(기사/이슈)을
        # 더한다. 건수 자체도 job_key별로 다른 값을 본다(_confirmed_count() 참고 —
        # insight는 processed_count가 아니라 실제로 확정된 Insight 개수를 센다).
        # 🔴 2026-09-16 "SET-010 검토 단위" 절 13번 — finished_at이 아니라
        # confirmed_at을 쓴다(위 _job_finished_today()와 같은 이유).
        prefix, when = _today_or_past(run_job.confirmed_at or run_job.finished_at)
        unit = CONFIRMED_UNIT_BY_JOB.get(job_key, "")
        count = _confirmed_count(run_job, job_key)
        count_text = f"{unit} {count}건" if unit else f"{count}건"
        summary = f"{prefix} {when} 확정, {count_text}"
    elif run_job.status == RunJob.STATUS_CANCELED:
        # 🔴 취소됨은 "상태가 아니라 사건"이고(같은 문서 5번), 사실은 요약 줄에
        # 남긴다 — 재료는 취소 뒤에도 그대로 남으므로 배지(todo/clear)는 재료
        # 유무로 이미 따로 정해져 있다.
        # 🔴 같은 계약(13차 개정 ②) — "{오늘|지난} 취소 {시각|날짜}, N건"(사고 색이
        # 아니라 사람이 의도해 누른 정상 동작이라는 사실만 말한다). 건수는 그
        # 배치의 크기(processed_count)이지 지금 남은 재료가 아니다.
        if not run_job.finished_at:
            summary = "지난 실행을 취소했어요"
        else:
            prefix, when = _today_or_past(run_job.finished_at)
            unit = CONFIRMED_UNIT_BY_JOB.get(job_key, "")
            count_text = f"{unit} {run_job.processed_count}건" if unit else f"{run_job.processed_count}건"
            summary = f"{prefix} {when} 취소, {count_text}"
    elif run_job.status == RunJob.STATUS_DONE:
        # 🔴 2026-09-15 PE 개정 — 조건을 GATED_JOB_KEYS 소속에서 ZERO_TARGET_SUMMARY_BY_JOB
        # 소속으로 바꿨다. 종전엔 "대상 0건이 review로 잘못 떨어지는 교착을 막는다"는
        # GATED 전용 사고를 막는 코드였는데, 뉴스룸 3단계(newsroom_compose)는 게이트가
        # 없어도(휴먼 인 더 루프가 없어 GATED_JOB_KEYS에 들지 않는다) 대상 0건이
        # 완료로 정상 처리되는 job이라(정책 12-3 (a), LLM 없이 고정 문구로 끝난다)
        # 같은 특수 요약이 필요하다. ZERO_TARGET_SUMMARY_BY_JOB에 있다는 사실 자체가
        # "이 job은 0건일 때 일반 문구로는 부족하다"는 신호이므로, 그 멤버십 하나로
        # 판정을 옮기면 GATED 여부와 무관하게 옳다 — cleanup/insight/weekly/monthly는
        # 여전히 GATED이자 이 dict에도 있어 동작이 그대로다.
        if job_key in ZERO_TARGET_SUMMARY_BY_JOB and run_job.target_count == 0:
            summary = ZERO_TARGET_SUMMARY_BY_JOB.get(job_key, "처리할 대상이 없었어요")
        elif job_key in ("collect", "newsroom_collect"):
            # 🔴 15차 개정 ⑦번 핵심 — processed_count(키워드 수, 실측 19건 고정)를
            # 쓰지 않는다. 실제로 새로 저장된 기사 수를 별도로 센다(위 헬퍼 참고).
            prefix, when = _today_or_past(run_job.finished_at)
            count = (
                _collect_article_count(run_job) if job_key == "collect"
                else _newsroom_collect_article_count(run_job)
            )
            count_text = "새 자료 없음" if count == 0 else f"새 자료 {count}건"
            summary = f"{prefix} {when} 수집, {count_text}"
        elif job_key == "newsroom_compose":
            # 🔴 processed_count가 이미 "그 발송문이 담은 기사 수"라 그대로 쓴다
            # (_run_newsroom_compose()가 len(targets)로 채운다) — 단위 낱말만 더한다.
            prefix, when = _today_or_past(run_job.finished_at)
            summary = f"{prefix} {when} 작성, 기사 {run_job.processed_count}건"
        elif job_key == "newsroom_filter":
            # 🔴 2026-09-16 PD 19차 개정 ⑧번 — 종전에는 이 값이 화면에 노출되지
            # 않았다(_newsroom_jobs_context()가 채널 누적("통과 N건, 제외 N건")으로
            # 항상 덮어썼는데, 그 값이 "제외 296건"처럼 채널이 살아온 전체 기간의
            # 합이라 어느 실행에도 속하지 않았다 — 15차 규약 위반). RunJob의
            # target_count/processed_count만으로 "그 실행 한 번"을 정확히 말할 수
            # 있어(마이그레이션 불필요) 이제 여기서 직접 만들고, 호출부는 더 이상
            # 덮어쓰지 않는다.
            prefix, when = _today_or_past(run_job.finished_at)
            summary = f"{prefix} {when} 선별, 기사 {run_job.processed_count}건"
        else:
            # 방어적 기본값 — 위 갈래에 없는 job_key가 DONE으로 여기 닿으면(새
            # job_key를 추가하며 이 분기를 깜빡한 경우) 아무 값도 없는 것보다는
            # 낫다는 최소한의 안전망이다.
            summary = f"마지막 실행 {timezone.localtime(run_job.finished_at):%m/%d %H:%M}, {run_job.processed_count}건"
    else:
        # RunJob.STATUS_PENDING — 실제 실행 경로(start_run/run_now)는 RunJob을 항상
        # STATUS_RUNNING으로 만들어 여기 닿지 않는다(방어적으로만 남긴다).
        summary = ""
    return {"state": state, "state_label": state_label, "summary": summary}


def _current_running_job():
    """지금 시스템 전체에서 진행중인 RunJob(있으면 그 인스턴스, 없으면 None).
    run.html/_run_graph.html의 running_job 컨텍스트 키 그대로다 — 두 템플릿 모두
    이 값을 진위값으로만 쓴다(속성 접근 없음). 읽기 전에 하트비트가 끊긴 진행중
    RunJob을 먼저 중단됨으로 정리한다(감시 프로세스 없이 읽는 쪽이 판정, 문서
    3-(e))."""
    from services.runner import mark_stale_running_as_stopped
    mark_stale_running_as_stopped()
    return RunJob.objects.filter(status=RunJob.STATUS_RUNNING).order_by("-started_at").first()


def _stuck_items():
    """SET-010 반복 실패 자료 지목(docs/planning.md 「SET-010 검토 단위」 9번,
    design.md 23차 개정 ②) — `#run-graph` 맨 위 주황 배너가 읽는 최상위 키.
    job dict가 아니라 그래프 전체가 직접 읽는다(노드 안에는 자리가 없다, 위 문서
    ②-2).

    🔴 자동 건너뛰기를 만들지 않는다 — 이 함수는 지목만 하고 아무것도 통과시키지
    않는다. B(미판정)가 0이 되어야 검토가 열리는데, 같은 자료가 계속 실패하면
    B가 영영 안 줄어드는 문제를 사람이 눈으로 보고 손을 쓰게 하는 것이 전부다.

    지금은 조사 2단계(cleanup)만 담는다 — News.classify_fail_count가 그 단계의
    실패만 센다(services/runner.py._run_cleanup()). step_label은 RUN_JOB_LABELS를
    그대로 참조한다 — 노드 라벨과 글자 그대로 같아야 한다는 계약을 상수 하나
    공유로 지킨다."""
    from services.runner import cleanup_ab_split

    _, b_qs = cleanup_ab_split()
    stuck = b_qs.filter(classify_fail_count__gte=STUCK_FAIL_THRESHOLD).order_by(
        "-classify_fail_count", "pk",
    )
    return [
        {
            "step_label": RUN_JOB_LABELS["cleanup"],
            "title": news.title,
            "source": news.source_domain,
            "published_at": news.published_at,
            "fail_count": news.classify_fail_count,
        }
        for news in stuck
    ]


def _run_graph_context():
    """`#run-graph` 조각을 그리는 네 뷰(전체 페이지, 3초 폴링, 실행 응답, 중단
    응답)가 공유하는 컨텍스트. 🔴 한 곳에 모은 이유 — stuck_items를 한쪽에만
    채우면 폴링이 돌 때마다 배너가 깜빡이며 사라진다(design.md 23차 개정 ②-2)."""
    return {
        "graph_url": reverse("setting_run_graph"),
        "running_job": _current_running_job(),
        "research_jobs": _research_jobs_context(),
        "newsroom_jobs": _newsroom_jobs_context(),
        "stuck_items": _stuck_items(),
        "stuck_log_url": reverse("setting_logs"),
    }


def _insight_block_reason() -> str:
    """3단계(주요 이슈) 선행 잠금 사유. 빈 문자열이면 잠기지 않는다(docs/planning.md
    "3~5단계를 LLM으로 옮기는 설계" 2번 표, PM 설계 "선행 미완은 경고가 아니라 버튼
    잠금이다"). 순서가 뜻을 가진다 — 먼저 걸리는 조건의 문구가 화면에 뜬다.

    🔴 2026-09-16 "SET-010 검토 단위" 절 확정(PD 19차 개정 ④번) — 두 조건으로
    줄었다. 종전 두 번째 조건("확정되지 않은 cleanup 배치가 있는가")은 커버리지
    조건(uncovered_count)을 지키기 위한 방어였는데, cleanup이 A/B로 넘어가면서
    그 조건 자체가 없어졌다(services/runner.py cleanup_ab_split() 참고) — 미검증
    News가 개별로 삭제돼도 A/B는 News 쪽에서 직접 세므로 첫 조건이 이미 정확하다.
    첫 조건 문구도 "2단계를 먼저 끝내 주세요"로 다음 행동을 말하게 바꿨다."""
    unverified_count = _unverified_news_count()
    if unverified_count:
        return f"아직 정리되지 않은 뉴스가 {unverified_count}건 있어요. 2단계를 먼저 끝내 주세요"

    from services.runner import insight_ab_split
    _, unassigned_qs = insight_ab_split()
    if not unassigned_qs.exists():
        # 🔴 2026-09-17 낱말 통일 — "묶을"을 "그룹화할"로 바꿨다(위
        # REVIEW_STEP_SUMMARY_BY_JOB 주석 참고).
        return "이슈로 그룹화할 뉴스가 없어요"

    return ""


def _unverified_news_count() -> int:
    """미검증 News 건수(A+B, docs/planning.md "SET-010 검토 단위" 0-1) — 위
    _insight_block_reason()의 첫 조건과 SET-006 로그가 같은 값을 본다."""
    return News.objects.filter(status=News.STATUS_UNVERIFIED).count()


def _cleanup_backlog():
    """SET-010 2단계(cleanup) 노드의 할 일 줄(PD 20차 개정 ②③, 19차 ③번의 "완료/전체"
    빗금 서식을 덮는다 — 사용자가 `67/67`을 "67건 중 67개를 더 해야 한다"로
    읽었다). services.runner.cleanup_ab_split()·cleanup_today_flow() 하나만
    본다 — 배지·버튼·검토 화면·흐름 줄과 같은 정본이라 수가 어긋나지 않는다.

    상태별 서식(20차 ⑨번 PE 인계, 22차 개정 ②번 — 「기사」에서 「자료」로):
      B > 0(todo)        "판정할 자료 {B}건[, 이전 {B 중 오늘 수집분이 아닌 수}건]"
      B = 0, A > 0(review) "검토할 자료 {A}건" — 🔴 동사가 바뀌고 세는 것도 A다
      A = B = 0(clear)    "판정할 자료 0건"

    🔴 "이전 N건" 조각은 0이면 붙이지 않는다(어제 것이 섞이는 것은 예외 상황이라
    예외일 때만 말한다) — cleanup_today_flow()가 계산한 "오늘 수집분 중 대기(B)"를
    전체 B에서 빼서 구한다. 오늘 수집이 0건인 날은 B 전체가 "오늘 수집분이
    아닌" 것이므로 carried_over == b_count다.

    🔴 2026-09-17 PD 25차 개정 — A=B=0(할 일 수 0)이면 (None, None)을 반환한다.
    종전엔 "판정할 자료 0건"을 그대로 냈지만, 20차 ③이 "흐름 줄의 마지막
    갈래 대기가 할 일 줄과 같은 것을 센다"고 못박아 둔 이상 할 일이 0이면
    대기도 반드시 0이라 판정 자리가 둘로 갈릴 수 없다(_insight_backlog() 주석과
    같은 근거). 호출부가 이 반환값으로 backlog·flow를 함께 켜고 끈다.

    반환값은 (backlog, backlog_title) 튜플. 할 일이 있으면 항상 채워진
    문자열이다(빈 문자열이 아니다). 호출부가 job["backlog"]/job["backlog_title"]에
    그대로 넣는다."""
    from services.runner import cleanup_ab_split, cleanup_today_flow

    a_qs, b_qs = cleanup_ab_split()
    a_count, b_count = a_qs.count(), b_qs.count()

    if a_count == 0 and b_count == 0:
        return None, None

    if b_count > 0:
        flow = cleanup_today_flow()
        today_waiting = flow["waiting"] if flow else 0
        carried_over = max(b_count - today_waiting, 0)
        backlog = f"판정할 자료 {b_count}건"
        if carried_over:
            backlog += f", 이전 {carried_over}건"
            title = f"미검증 {b_count}건 가운데 오늘 수집이 아닌 것이 {carried_over}건이에요"
        else:
            title = f"미검증 {b_count}건을 아직 판정하지 않았어요"
        return backlog, title

    # 🔴 review 상태 — 버튼이 "결과 검토하기"로 바뀌는 것과 같은 말을 해야
    # 한다(20차 ⑨번 "동사가 바뀌고 세는 것도 A다"). a_count == 0이면 위에서
    # 이미 (None, None)으로 걸러졌으므로 여기 도달하면 a_count > 0이다.
    return f"검토할 자료 {a_count}건", f"확정 대기 {a_count}건이 검토를 기다리고 있어요"


def _cleanup_flow():
    """SET-010 2단계(cleanup) 노드의 흐름 줄(PD 20차 개정 ② flow, 신설, 22차 개정
    ③번 단위 규칙) — "오늘 {모수}건 → 제외 n건, 통과 n건, 검토 n건, 대기 n건" 형태.
    0인 갈래는 적지 않는다. services.runner.cleanup_today_flow()가 낸 네 수를
    그대로 문장으로 옮기기만 한다 — 수를 다시 세지 않는다(두 벌이 되면 할 일
    줄과 어긋난다).

    🔴 22차 ③번 — 갈래(parts)가 넷이면 단위(「건」)를 전부 뺀다. 넷 + 단위는
    256px로 240px 예산을 넘겨 truncate가 맨 끝 "대기 n"을 자른다.

    오늘 수집이 0건이면 (None, None)을 반환한다 — 그날은 "오늘 흐름"이 없는
    것이 사실이라 줄 자체를 내리지 않는다(17차 "작업이 없으면 억지로 띄우지
    않는다" 원칙을 여기서도 지킨다)."""
    from services.runner import cleanup_today_flow

    flow = cleanup_today_flow()
    if flow is None:
        return None, None

    labeled = []
    if flow["deleted"]:
        labeled.append(("제외", flow["deleted"]))
    if flow["verified"]:
        labeled.append(("통과", flow["verified"]))
    if flow["review"]:
        labeled.append(("검토", flow["review"]))
    if flow["waiting"]:
        labeled.append(("대기", flow["waiting"]))
    unit = "" if len(labeled) >= 4 else "건"
    parts = [f"{label} {count}{unit}" for label, count in labeled]
    flow_str = f"오늘 {flow['total']}건 → " + ", ".join(parts) if parts else f"오늘 {flow['total']}건"

    # 🔴 2026-09-16 — 흐름 줄 자체(flow_str)의 "제외 N"은 두 주체를 쪼개지 않는다
    # (design.md "SET-010 · 실행" 21차 개정 ⑥번 — 줄 길이 예산이 없고, 이 줄이
    # 답하는 물음은 "그 수가 어디서 나왔나"이지 "누가 판정했나"가 아니다). 대신
    # flow_title(마우스 올림)에만 한 조각을 더한다 — 문장이라 자리가 있다.
    today = timezone.localtime(timezone.now()).date()
    rule_deleted_today = DeletedNewsRecord.objects.filter(
        collected_at__date=today, judged_by=DeletedNewsRecord.JUDGED_BY_CODE_AI_KEYWORD_RULE,
    ).count()
    if rule_deleted_today:
        flow_title = (
            f"오늘 수집한 {flow['total']}건 가운데 {flow['deleted']}건을 제외했고 그중 "
            f"{rule_deleted_today}건은 코드 규칙이 걸렀어요. {flow['verified']}건이 검증을 통과했어요"
        )
    else:
        flow_title = (
            f"오늘 수집한 {flow['total']}건 가운데 {flow['deleted']}건을 제외하고 "
            f"{flow['verified']}건이 검증을 통과했어요"
        )
    return flow_str, flow_title


def _insight_backlog():
    """SET-010 3단계(주요 이슈) 노드의 할 일 줄(PD 20차 개정 ②③, 22차 개정 ⑦번) —
    "묶을 기사 N건" 단일 서식이다(19차의 "배정 82/140" 빗금 서식, 20차의 "통합할
    기사"는 폐기). services.runner.
    insight_ab_split() 하나만 본다 — _insight_block_reason()·_job_has_work()·이
    줄이 전부 같은 쿼리를 봐서 배지·버튼·할 일 줄이 어긋나지 않는다.

    🔴 cleanup과 달리 review 상태에서 동사가 바뀌지 않는다(20차 ⑨번 "3단계와
    교보 2단계에는 이 갈래가 없다") — insight의 "review"(확정 대기 초안이
    쌓인 상태)는 cleanup의 B=0 같은 "미배정이 0이 됐다"는 뜻이 아니다. 다음
    배치를 위한 미배정 후보가 여전히 남아 있을 수 있어, 상태와 무관하게 항상
    같은 문장을 쓴다.

    🔴 2026-09-17 낱말 통일(REVIEW_STEP_SUMMARY_BY_JOB 주석 참고) — "묶을"을
    "그룹화할"로, "통합하지"를 "그룹화하지"로 바꿨다.

    🔴 2026-09-17 PD 25차 개정 — 할 일 수(unassigned_count)가 0이면 (None, None)을
    반환한다. 종전엔 0이어도 "그룹화할 기사 0건"을 그대로 냈는데, 20차 ③이
    "마지막 갈래 대기가 할 일 줄과 같은 것을 센다"고 못박아 둔 이상 할 일이
    0이면 대기도 반드시 0이라 판정 자리가 둘(할 일 줄, 흐름 줄)로 갈릴 수
    없다. state=='clear'로 가르지 않는다 — clear의 뜻이 단계마다 달라서다
    (교보 4단계는 "준비 중"인데도 clear). 거르는 것은 어디까지나 "수 0"이다.
    호출부(_run_job_display 조립부)가 이 반환값을 보고 backlog·flow를 함께
    켜고 끈다 — 흐름 줄을 따로 판정하지 않는다.

    반환값은 (backlog, backlog_title) 튜플. 할 일이 있으면 항상 채워진
    문자열이다."""
    from services.runner import insight_ab_split

    assigned_qs, unassigned_qs = insight_ab_split()
    assigned_count, unassigned_count = assigned_qs.count(), unassigned_qs.count()
    if unassigned_count == 0:
        return None, None
    total = assigned_count + unassigned_count
    backlog = f"그룹화할 기사 {unassigned_count}건"
    title = f"검증된 뉴스 {total}건 가운데 아직 그룹화하지 않은 것이 {unassigned_count}건이에요"
    return backlog, title


def _insight_flow():
    """SET-010 3단계 노드의 흐름 줄(PD 20차 개정 ② flow, 신설, 22차 개정 ⑦번 —
    "검증 완료 {전체}건 → 이슈 반영 n건, 대기 n건" 형태(누적 축이라 "완료"로
    시작한다, 2단계의 "오늘"과 대비된다 — 20차 ③번 "두 글자만 봐도 모수의 성격이
    갈린다"). 0인 갈래는 적지 않는다.

    🔴 2026-09-17 낱말 통일 — "통합됐어요"를 "그룹화됐어요"로 바꿨다.

    🔴 2026-09-17 PD 25차 개정 — 이 함수는 더 이상 스스로 "보일지 말지"를
    판단하지 않는다. 호출부가 _insight_backlog()의 결과(할 일 수 0이면
    None)로 이 함수의 호출 여부까지 함께 정한다 — 흐름 줄을 따로 판정하지
    않는다는 원칙이 여기 있다."""
    from services.runner import insight_ab_split

    assigned_qs, unassigned_qs = insight_ab_split()
    assigned_count, unassigned_count = assigned_qs.count(), unassigned_qs.count()
    total = assigned_count + unassigned_count

    parts = []
    if assigned_count:
        parts.append(f"이슈 반영 {assigned_count}건")
    if unassigned_count:
        parts.append(f"대기 {unassigned_count}건")
    flow = f"검증 완료 {total}건 → " + ", ".join(parts) if parts else f"검증 완료 {total}건"
    flow_title = f"검증된 뉴스 {total}건 가운데 {assigned_count}건이 이슈로 그룹화됐어요"
    return flow, flow_title


def _job_has_work(job_key: str) -> bool:
    """SET-010 노드 배지 "할 일이 있나" 축 판정(docs/planning.md "SET-010 노드
    배지" 1번 표) — job_key 하나로 위임한다. _run_job_display()의 호출부(그래프,
    아래 _research_jobs_context()/_newsroom_jobs_context())와
    _run_review_context()(검토 화면 머리글)가 이 함수 하나를 같이 써서, 같은
    job_key에 서로 다른 답을 내지 않게 한다(같은 문서 8-2 "판정이 두 벌이 되면
    배지와 버튼이 어긋난다").

    축은 노드마다 다르다 — collect류는 항상 True(2026-09-16, 날짜 축 폐기 — 아래
    분기 참고), 재료(cleanup·newsroom_filter), 기간(weekly·monthly), 그리고
    insight(새 재료)·newsroom_compose(마지막 발송문 이후 새 통과 기사, 단 선행으로
    pending 잔여를 본다)는 각각 예외 규칙을 따로 갖는다. newsroom_send(9번)는
    만들지 않기로 확정돼 있어(정책 12-0) 이 표에 없다 — 항상 False다."""
    today = _today_local()
    if job_key in ("collect", "newsroom_collect"):
        # 🔴 2026-09-16 사용자 결정 — 날짜 축을 버린다. 수집은 눌러 봐야 새 기사가
        # 있는지 알 수 있다(CollectionLog 실측 — 같은 날 여러 번, 신규 0건 포함해
        # 반복 실행되는 게 정상 운영이었다). "오늘 이미 완료했다"는 이유로 잠그면
        # 그날 두 번째 이후 수집을 막는 잘못된 신호가 된다. 항상 todo다.
        return True
    if job_key == "cleanup":
        from services.runner import cleanup_ab_split
        return cleanup_ab_split()[1].exists()  # B(미판정) > 0
    if job_key == "insight":
        # 🔴 2026-09-16 "SET-010 검토 단위" 절 11번 — 3단계 대상이 "직전 확정
        # 이후 새로 검증된 것"(증분형)에서 "탈락 표식 없는 미배정 전체"로
        # 바뀌면서, 이 판정과 _insight_block_reason()의 마지막 조건이 완전히
        # 같은 물음이 됐다. 별도 함수(_insight_has_new_material())를 두지 않는다.
        return not _insight_block_reason()
    if job_key == "weekly":
        from services.report_periods import insights_in_period, target_week
        date_from, date_to = target_week(today)
        if not insights_in_period(date_from, date_to).exists():
            return False
        return not Report.objects.filter(period_type="weekly", date_from=date_from).exists()
    if job_key == "monthly":
        from services.report_periods import insights_in_period, target_month
        date_from, date_to = target_month(today)
        if not insights_in_period(date_from, date_to).exists():
            return False
        return not Report.objects.filter(period_type="monthly", date_from=date_from).exists()
    if job_key == "newsroom_filter":
        room = _target_newsroom()
        return bool(room and room.pending_count > 0)
    if job_key == "newsroom_compose":
        room = _target_newsroom()
        return bool(room) and _newsroom_compose_has_new_material(room)
    return False


# 게이트 단계는 "완료"가 아니라 "확정까지 눌렀다"일 때만 그 단계를 지나온 것이다
# (docs/design.md 15차 개정 ④번) — GATED_JOB_KEYS를 그대로 재사용한다(새 목록을
# 만들지 않는다, _clear_can_run() 등과 같은 원칙).
def _job_finished_today(job_key: str) -> bool:
    """SET-010 연결선의 "앞 단계를 오늘 지나왔다" 판정(docs/design.md 15차 개정 ①④).

    게이트 단계(cleanup/insight/weekly/monthly)는 오늘 STATUS_CONFIRMED인 RunJob이
    하나라도 있으면 참이다 — 제안만 내고 검토를 기다리는 중(STATUS_DONE, review
    배지)은 사람이 아직 확정을 누르지 않아 그 단계를 지나온 것이 아니다. 그 밖
    (collect·newsroom_collect·newsroom_filter·newsroom_compose)은 오늘
    STATUS_DONE인 RunJob이 하나라도 있으면 참이다 — 이 넷은 확정 게이트가 없어
    완료가 곧 끝이다.

    🔴 2026-09-16 PE 재수정(코디네이터 실측 지적) — "최신 RunJob 하나"가 아니라
    "오늘 그 사건이 있었던 RunJob이 하나라도 있는가"(exists)로 바꿨다. 최신
    배치 하나만 보면, 오늘 이미 확정한 배치가 있어도 그보다 나중에 시작된 다른
    배치(옛 방식으로 확정돼 confirmed_at이 NULL인 배치 등)가 "가장 최근" 자리를
    차지하는 순간 "오늘 지나왔다"가 거짓이 된다 — 실측: pk131(확정됨,
    confirmed_at NULL, 13:05 시작)이 pk130(확정됨, confirmed_at 오늘 14:51)보다
    started_at이 최신이라, 종전 코드는 pk131만 보고 거짓을 냈다(2→3 화살표가
    회색으로 남는 사고). 검토 경로를 "확정 대기 전부"로 바꾼 것과 같은 이유로
    여기도 "최근 하나"에서 "존재하는가"로 바꾼다.

    🔴 confirmed_at이 NULL인 옛 확정 배치를 소급해 채우지 않는다 — exists() 방식은
    그 배치가 "오늘 확정된 것이 아니다"라는 사실을 소급 없이도 그대로 정확히
    말한다(그 배치가 오늘 확정이 아니었다는 것 자체가 맞는 값이라 채울 이유가
    없다)."""
    if job_key in GATED_JOB_KEYS:
        return RunJob.objects.filter(
            job_key=job_key, status=RunJob.STATUS_CONFIRMED, confirmed_at__date=_today_local(),
        ).exists()
    return RunJob.objects.filter(
        job_key=job_key, status=RunJob.STATUS_DONE, finished_at__date=_today_local(),
    ).exists()


def _weekly_job_context():
    """run.html/_run_graph.html의 research_jobs["weekly"](4단계 주간 보고서).

    🔴 대상 주는 services/report_periods.target_week() 단 하나로 계산한다 — 확정
    시점의 Report.date_from/date_to 저장도 services/runner.py가 같은 함수를 쓴다
    (docs/planning.md "3~5단계를 LLM으로 옮기는 설계" 2-1-(d) "뷰가 날짜를 따로
    계산하지 않는다"). "대상 기간에 Insight가 0건이다" 판정도 같은 문서의
    insights_in_period()를 그대로 쓴다. 주차 이름은 report_periods._week_number_in_month()
    를 그대로 쓴다 — 새로 만들지 않는다.

    🔴 2026-09-15 10차 개정, 22차 개정(문구, 「금요일」 폐기·③번 24자 예산) —
    summary가 「언제 썼다」가 아니라 「언제부터 작성할 수 있다」를 말한다
    (docs/design.md "SET-010 · 실행" 10차 개정 ①②④번). 세 갈래다.
      - 재료 없음(대상 주 Insight 0건): "3단계 이슈를 확정하면 열려요"
      - 때가 아님(대상 주 Report가 이미 있음): "{다음 주차} 보고서는 {다음
        날짜}부터 작성할 수 있어요" — 다음 대상 주는 date_to + 7일이다.
        🔴 「금요일」은 넣지 않는다 — 24자(240px) 예산을 넘겨 두 줄로 꺾인다
        (design.md 22차 ③번).
      - 열려 있음: "{이번 주차} 보고서를 지금 작성할 수 있어요"
    block_reason(툴팁)도 함께 바뀐다 — "이번 주"처럼 오늘 기준으로 흔들리는 말 대신
    주차 이름을 박아 "{이번 주차} 보고서가 이미 있어요"로 통일한다(9차가 화면
    안팎을 갈랐던 두 문구가 10차에서 하나로 합쳐졌다 — 근거는 design.md 10차
    개정 ③번).

    🔴 todo/clear일 때만 summary를 덮는다(2026-09-15 "SET-010 노드 배지" 개정 —
    done/idle 두 값이 이 축으로 합쳐졌다) — running은 summary가 빈 문자열이어야
    진행 표시가 그 자리를 받고(_run_job_display() 참고), stopped/failed/review는
    지금 벌어진 일을 말하는 게 더 급하다.

    🔴 can_run은 여기서 계산하는 값 그대로가 곧 "할 일이 있나" 축 판정
    (has_work)이다 — _job_has_work("weekly")도 같은 두 조건(대상 주 Insight
    존재, 그 주 Report 부재)을 본다(docs/planning.md "SET-010 노드 배지" 8-2).
    여기서 다시 계산하는 이유는 block_reason·summary_override 문구를 만들려면
    갈래(재료 없음/때가 아님/열려 있음)를 알아야 해서이고, has_work용으로
    _job_has_work()를 따로 부르지 않는 것은 같은 쿼리를 두 번 던지지 않기
    위해서다 — 이 함수가 계산한 can_run을 그대로 has_work로 넘긴다."""
    from services.report_periods import _week_number_in_month, insights_in_period, target_week

    today = _today_local()
    date_from, date_to = target_week(today)

    can_run, block_reason = True, ""
    if not insights_in_period(date_from, date_to).exists():
        can_run, block_reason = False, "이번 주에 만들어진 이슈가 없어요"
        summary_override = "3단계 이슈를 확정하면 열려요"
    else:
        existing = Report.objects.filter(period_type="weekly", date_from=date_from).first()
        if existing:
            can_run = False
            week_no = _week_number_in_month(date_to)
            block_reason = f"{date_to.month}월 {week_no}주차 보고서가 이미 있어요"
            next_to = date_to + timedelta(days=7)
            next_week_no = _week_number_in_month(next_to)
            summary_override = (
                f"{next_to.month}월 {next_week_no}주차 보고서는 {next_to.month}/{next_to.day}부터 "
                "작성할 수 있어요"
            )
        else:
            week_no = _week_number_in_month(date_to)
            summary_override = f"{date_to.month}월 {week_no}주차 보고서를 지금 작성할 수 있어요"

    display = _run_job_display("weekly", can_run)
    job = display or {"state": "todo" if can_run else "clear", "state_label": STATE_LABELS["todo" if can_run else "clear"], "summary": ""}

    if job["state"] in ("todo", "clear"):
        job["summary"] = summary_override

    job.update({
        "can_run": can_run,
        "block_reason": block_reason,
        "warning": "",
        "confirm_text": "",
        "run_url": reverse("setting_run_start", args=["weekly"]),
        "review_url": reverse("setting_run_review", args=["weekly"]),
    })
    return job


def _monthly_job_context():
    """run.html/_run_graph.html의 research_jobs["monthly"](5단계 월간 보고서).
    _weekly_job_context()와 같은 계약이되 갈래가 하나뿐이다 — 대상 월을 직전 달로
    정의하는 순간 "대상 월이 끝났는가"는 정의상 항상 참이라 "아직 열릴 때가 아니에요"에
    해당하는 조건이 없다(설계 2-1-(b) 2번).

    🔴 2026-09-15 10차 개정, 22차 개정(문구, 「결산」 폐기) — weekly와 같은 세
    갈래(design.md 10차 개정 ①②④번).
      - 재료 없음: "3단계 이슈를 확정하면 열려요"
      - 때가 아님(대상 월 Report가 이미 있음): "{이번 달}월 월간 보고서는
        {다음 달 1일}부터 작성할 수 있어요" — target_month()는 "직전 달"을
        대상으로 삼으므로, 다음에 열리는 월간 보고서의 대상 달은 정확히
        today.month(오늘이 속한 달)이고 그 시작일은 다음 달 1일이다.
      - 열려 있음: "{대상 월}월 월간 보고서를 지금 작성할 수 있어요"

    🔴 can_run이 그대로 "할 일이 있나" 축 판정(has_work)이다 —
    _weekly_job_context()와 같은 이유(위 docstring 참고)로 _job_has_work()를
    따로 부르지 않는다."""
    from services.report_periods import insights_in_period, target_month

    today = _today_local()
    date_from, date_to = target_month(today)

    can_run, block_reason = True, ""
    if not insights_in_period(date_from, date_to).exists():
        can_run, block_reason = False, "지난달에 만들어진 이슈가 없어요"
        summary_override = "3단계 이슈를 확정하면 열려요"
    else:
        existing = Report.objects.filter(period_type="monthly", date_from=date_from).first()
        if existing:
            can_run = False
            block_reason = f"{date_from.month}월 월간 보고서가 이미 있어요"
            # target_month()가 "직전 달"을 대상으로 삼으므로, 다음에 열리는 월간
            # 보고서의 대상 달은 오늘이 속한 달(today.month)이고 그 시작일은 다음 달
            # 1일이다.
            next_month = today.month + 1 if today.month < 12 else 1
            summary_override = f"{today.month}월 월간 보고서는 {next_month}/1부터 작성할 수 있어요"
        else:
            summary_override = f"{date_from.month}월 월간 보고서를 지금 작성할 수 있어요"

    display = _run_job_display("monthly", can_run)
    job = display or {"state": "todo" if can_run else "clear", "state_label": STATE_LABELS["todo" if can_run else "clear"], "summary": ""}

    if job["state"] in ("todo", "clear"):
        job["summary"] = summary_override

    job.update({
        "can_run": can_run,
        "block_reason": block_reason,
        "warning": "",
        "confirm_text": "",
        "run_url": reverse("setting_run_start", args=["monthly"]),
        "review_url": reverse("setting_run_review", args=["monthly"]),
    })
    return job


def _research_jobs_context():
    """run.html/_run_graph.html의 research_jobs(AI 시장 조사 축, 5개 키 고정)."""
    has_work_collect = _job_has_work("collect")
    run_display = _run_job_display("collect", has_work_collect)
    if run_display:
        collect_job = run_display
    else:
        # 🔴 RunJob이 한 번도 없었던 레거시 경로 — CollectionLog만 있다. "오늘"
        # 판정도 우선순위 3번(오늘 벌어진 실패)과 같은 규칙을 그대로 적용한다.
        latest = CollectionLog.objects.order_by("-started_at").first()
        if latest and latest.status == "fail" and _is_today_local(latest.started_at):
            collect_job = {
                "state": "failed", "state_label": STATE_LABELS["failed"],
                "summary": f"마지막 수집 {timezone.localtime(latest.started_at):%m/%d %H:%M}",
            }
        else:
            state = "todo" if has_work_collect else "clear"
            collect_job = {
                "state": state, "state_label": STATE_LABELS[state],
                "summary": (
                    f"마지막 수집 {timezone.localtime(latest.started_at):%m/%d %H:%M}" if latest else ""
                ),
            }

    jobs = {
        "collect": {
            **collect_job,
            "can_run": True,
            "block_reason": "",
            "warning": "",
            "confirm_text": "",
            "run_url": reverse("setting_run_start", args=["collect"]),
            "review_url": "",
        },
    }

    # 2단계 뉴스 정리 — 2026-09-14 2라운드에서 실행 버튼을 연다(services/runner.py
    # IMPLEMENTED_JOB_KEYS에 "cleanup" 추가와 짝을 이룬다). 완료(STATUS_DONE)면
    # _run_job_display()가 GATED_JOB_KEYS 분기로 state="review"를 내려, 노드가 자동으로
    # "결과 검토하기" 버튼으로 바뀐다(_run_node.html) — 여기서 따로 분기하지 않는다.
    has_work_cleanup = _job_has_work("cleanup")
    cleanup_display = _run_job_display("cleanup", has_work_cleanup)
    cleanup_job = cleanup_display or {
        "state": "todo" if has_work_cleanup else "clear",
        "state_label": STATE_LABELS["todo" if has_work_cleanup else "clear"],
        "summary": "",
    }
    # 🔴 2026-09-16 사용자 결정 — state=='clear'면 can_run도 False다(배지와 버튼이
    # 항상 같은 말을 한다). 종전엔 can_run이 상태와 무관하게 항상 True였다 —
    # 미검증 뉴스가 0건이라 배지가 "실행 대상 없음"인데 버튼은 열려 있는 실제 버그였다.
    cleanup_can_run = _clear_can_run(cleanup_job, CLEANUP_CLEAR_BLOCK_REASON)
    # 🔴 2026-09-16 PD 20차 개정 — 할 일 줄(backlog)과 흐름 줄(flow)을 running
    # 하나만 빼고 항상 내린다.
    # 🔴 2026-09-17 PD 25차 개정 — 할 일 수가 0이면(_cleanup_backlog()가
    # (None, None)을 반환하면) 흐름 줄도 함께 내리지 않는다. 흐름 줄을 따로
    # 판정하지 않는다 — backlog가 없는데 flow만 남으면(예: 오늘 수집·처리는
    # 있었지만 지금은 A=B=0으로 다 정리된 상태) 판정 자리가 둘로 갈린다.
    # backlog가 있을 때만 flow를 계산해 붙인다. flow는 그 안에서도 오늘 수집이
    # 0건이면 (None, None)일 수 있다(_cleanup_flow() 참고) — 이건 여전히 유효한
    # 별개의 "그날은 오늘 흐름이 없다"는 사실이라 그대로 둔다.
    if cleanup_job["state"] != "running":
        backlog, backlog_title = _cleanup_backlog()
        if backlog:
            cleanup_job["backlog"], cleanup_job["backlog_title"] = backlog, backlog_title
            flow, flow_title = _cleanup_flow()
            if flow:
                cleanup_job["flow"], cleanup_job["flow_title"] = flow, flow_title
    cleanup_job.update({
        "can_run": cleanup_can_run,
        "block_reason": cleanup_job.get("block_reason", ""),
        "warning": "",
        "confirm_text": "",
        "run_url": reverse("setting_run_start", args=["cleanup"]),
        "review_url": reverse("setting_run_review", args=["cleanup"]),
    })
    jobs["cleanup"] = cleanup_job

    # 3단계 주요 이슈 — GATED_JOB_KEYS에 "insight"가 있어 완료(STATUS_DONE)면
    # _run_job_display()가 그대로 state="review"를 내려 cleanup과 똑같이 "결과
    # 검토하기" 버튼으로 바뀐다 — 여기서 따로 분기하지 않는다.
    #
    # 🔴 2026-09-16 "SET-010 검토 단위" 절 확정 — has_work_insight(배지)와
    # insight_block_reason(버튼 잠금 사유)이 이제 같은 물음이다. 3단계 대상이
    # "직전 확정 이후 새로 검증된 것"(증분형)에서 "탈락 표식 없는 미배정
    # 전체"로 바뀌면서, has_work도 _insight_block_reason()을 그대로 위임해
    # 쓴다(_job_has_work() 참고) — "잔여는 있는데 새 재료는 없는" 중간 상태
    # 자체가 없어져 block_reason이 이제 clear일 때 항상 스스로 구체적인 사유를
    # 채운다.
    has_work_insight = _job_has_work("insight")
    insight_display = _run_job_display("insight", has_work_insight)
    insight_job = insight_display or {
        "state": "todo" if has_work_insight else "clear",
        "state_label": STATE_LABELS["todo" if has_work_insight else "clear"],
        "summary": "",
    }
    insight_job["block_reason"] = _insight_block_reason()
    # 🔴 block_reason이 이미 위에서 채워졌으므로(has_work=False면 반드시 비어
    # 있지 않다 — _job_has_work("insight")가 그 함수를 그대로 쓴다) 여기서
    # _clear_can_run()에 넘기는 대체 문구는 실제로 쓰일 일이 없다.
    insight_can_run = _clear_can_run(insight_job, "")
    # 🔴 PD 20차 개정 — 할 일 줄("그룹화할 기사 N건")과 흐름 줄("검증 완료
    # N건 → 이슈 반영 n, 대기 n"). cleanup과 같은 이유로 running 하나만 뺀다.
    # 🔴 2026-09-17 PD 25차 개정 — 할 일 수가 0이면(_insight_backlog()가
    # (None, None)을 반환하면) 흐름 줄도 함께 내리지 않는다(cleanup과 같은
    # 근거 — 위 _cleanup_backlog 호출부 주석 참고). backlog가 있을 때만 flow를
    # 계산해 붙인다.
    if insight_job["state"] != "running":
        backlog, backlog_title = _insight_backlog()
        if backlog:
            insight_job["backlog"], insight_job["backlog_title"] = backlog, backlog_title
            insight_job["flow"], insight_job["flow_title"] = _insight_flow()
    insight_job.update({
        "can_run": insight_can_run,
        "block_reason": insight_job["block_reason"],
        "warning": "",
        "confirm_text": "",
        "run_url": reverse("setting_run_start", args=["insight"]),
        "review_url": reverse("setting_run_review", args=["insight"]),
    })
    jobs["insight"] = insight_job

    # 4, 5단계 주간·월간 보고서 — 같은 날 뒤이은 라운드에서 실행 버튼을 연다
    # (services/runner.py IMPLEMENTED_JOB_KEYS에 "weekly"·"monthly" 추가와 짝을
    # 이룬다). can_run/block_reason/summary는 각 컨텍스트 함수가 전부 결정한다.
    jobs["weekly"] = _weekly_job_context()
    jobs["monthly"] = _monthly_job_context()

    # 🔴 15차 개정 ① — 연결선이 보는 "오늘 지나왔다" 판정. 다섯 노드 전부 같은
    # 함수 하나로 채운다(판정을 두 벌로 만들지 않는다).
    for key in jobs:
        jobs[key]["finished_today"] = _job_finished_today(key)
    return jobs


def _target_newsroom():
    """SET-010 교보 소식 1단계 수집의 대상 채널을 고른다. _setting_menu()/newsroom_nav가
    쓰는 "활성 채널이 1개면 그것" 규칙과 같은 방식이다(코디네이터 지시) — 채널이
    여러 개로 늘면 그때 다시 판단한다. 활성이 0개거나 2개 이상이면 어느 채널을 돌릴지
    정할 수 없으므로 None을 반환하고, 호출부가 그 이유를 block_reason으로 내려준다."""
    from apps.newsroom.models import Newsroom
    active_rooms = list(Newsroom.objects.filter(is_active=True))
    return active_rooms[0] if len(active_rooms) == 1 else None


def _newsroom_filter_backlog(room):
    """SET-010 교보 2단계 노드의 할 일 줄(PD 20차 개정 ②③, 22차 개정 ⑦번) —
    "선별할 기사 N건" 단일 서식이다(19차의 "판정 284/306" 빗금 서식, 20차의
    "판정할 기사"는 폐기). `room.pending_count`(apps/newsroom/models.py)와 같은
    조건을 쓴다 — SET-009가 거기서 같은 수를 보인다(docs/planning.md "뉴스룸"
    절 12-1 결정 (b)).

    🔴 2026-09-17 PD 25차 개정 — pending(할 일 수)이 0이면 (None, None)을
    반환한다. 종전 19차 개정은 "0건이어도 지우지 않는다"였지만, 20차 ③의
    "흐름 줄 마지막 갈래 대기가 할 일 줄과 같은 것을 센다"를 cleanup·insight와
    똑같이 여기도 적용한다 — 할 일이 0이면 흐름 줄의 대기도 반드시 0이라
    판정 자리가 둘로 갈릴 수 없다. 호출부가 이 반환값으로 backlog·flow를
    함께 켜고 끈다.

    반환값은 (backlog, backlog_title) 튜플. 할 일이 있으면 항상 채워진
    문자열이다."""
    total = room.articles.count()
    pending = room.pending_count
    if pending == 0:
        return None, None
    done = total - pending
    backlog = f"선별할 기사 {pending}건"
    title = f"채널 기사 {total}건 가운데 선별이 끝난 것이 {done}건이에요"
    return backlog, title


def _newsroom_filter_flow(room):
    """SET-010 교보 2단계 노드의 흐름 줄(PD 20차 개정 ② flow, 신설, 22차 개정
    ⑦번) — "누적 기사 {전체}건 → 선별 완료 n건, 대기 n건" 형태(누적 축). 0인
    갈래는 적지 않는다."""
    total = room.articles.count()
    pending = room.pending_count
    done = total - pending

    parts = []
    if done:
        parts.append(f"선별 완료 {done}건")
    if pending:
        parts.append(f"대기 {pending}건")
    flow = f"누적 기사 {total}건 → " + ", ".join(parts) if parts else f"누적 기사 {total}건"
    flow_title = f"채널 기사 {total}건 가운데 {done}건을 선별했어요"
    return flow, flow_title


def _newsroom_compose_has_new_material(room) -> bool:
    """SET-010 교보 3단계(발송문) 배지의 "새 기사" 판정(사용자 결정, 2026-09-16) —
    날짜 축("오늘 발송문이 아직 없나")을 버린다. 어제 만든 발송문과 오늘 통과분이
    같으면(재판정으로 새로 늘지 않았으면) 다시 실행해도 같은 문구를 또 만들 뿐이다
    — 실제로 09/15 16:24에 9건으로 발송문을 만들고 오늘도 passed가 그대로 9건인
    상태가 이 조건을 확인한 근거다.

    🔴 선행 조건(2단계 판정 전 기사가 남아 있으면 무조건 할 일 없음)도 여기서
    본다 — `_job_has_work("newsroom_compose")`와 `_newsroom_jobs_context()`가
    이 함수 하나를 같이 쓰므로, 선행 조건을 호출부마다 따로 검사하면 판정이
    다시 두 벌이 된다(2026-09-16 PM 지적, docs/planning.md "SET-010 노드 배지"
    8-2). `_newsroom_jobs_context()`는 이 함수와 별개로 pending_count를 다시
    조회하는데, 그건 block_reason 문구("판정 전 기사가 있어요…")를 만들기
    위해서일 뿐 has_work 판정 자체를 다시 하는 게 아니다.

    🔴 판정 시각 필드가 없다 — `NewsroomArticle`에는 filter_status가 언제
    passed로 바뀌었는지 기록하는 필드(judged_at 같은 것)가 없다(2026-09-16 PE
    실측, 모델 필드 전수 확인). 그래서 `_insight_has_new_material()`처럼 "마지막
    확정 시각 이후"를 시각 비교로 판정할 수 없다.

    대신 집합 비교를 쓴다 — `NewsroomMessage.articles`가 그 발송문을 만든 시점의
    통과 기사 집합을 이미 얼려 두므로(모델 docstring "생성 시점의 집합을 얼려
    둔다"), 지금 대상(통과 + 비중복) 집합에서 이미 보낸 기사를 빼고 남는 것이
    있으면 새 기사다. 시각 필드보다 이 편이 더 정확하다 — "판정 시각이 발송
    이후인가"는 근사이지만 "이미 어느 발송문에 담겼던 기사인가"는 정의 그 자체다.
    새 필드나 새 모델은 만들지 않는다.

    🔴 2026-09-16 PE 정정("SET-010 검토 단위" 절 12-(b)) — 기준점을 "마지막
    NewsroomMessage 하나"에서 "모든 NewsroomMessage의 포함 기사 합집합"으로
    바꿨다. 마지막 하나만 보면 그 앞 메시지에 담겼던 기사가 재판정 없이도 다시
    새 재료로 잡힌다 — 예를 들어 메시지 A(기사 1,2)를 만들고 메시지 B(기사 3)를
    만들면, 마지막 하나만 보는 종전 방식은 기사 1,2가 "B에 없다"는 이유로 다시
    새 재료가 된다. 실무에서 결과가 같을 때가 많아 드러나지 않았을 뿐 정의가
    틀려 있었다.

    마지막 발송문이 한 번도 없으면(첫 실행) 지금 대상이 하나라도 있으면 새
    재료로 친다.

    🔴 2026-09-17 PE 수정 — 판정 로직을 여기서 다시 계산하지 않고
    `Newsroom.compose_targets`(apps/newsroom/models.py)를 그대로 부른다.
    이 함수(배지)만 위 정의로 고쳐지고 실제 실행(`services/runner.py`의
    `_run_newsroom_compose()`)은 "통과 + 비중복" 전량을 그대로 쓰는 채로
    남아 있던 것이 갈라진 두 벌 — 그 결과 배지가 "새 재료 없음"이라 말해도
    실행하면 이미 보낸 기사까지 다시 담겼다(사용자가 화면에서 발견한 "14건에
    이전 회차까지 담김" 사고). 이제 이 함수와 `_run_newsroom_compose()` 둘 다
    같은 프로퍼티 하나를 부른다(PM 지시 "두 벌로 짜지 말 것")."""
    if room.pending_count > 0:
        return False
    return room.compose_targets.exists()


def _newsroom_jobs_context():
    """run.html/_run_graph.html의 newsroom_jobs(교보 소식 축, 4개 키 고정).
    1~3단계는 각각 apps/newsroom/services.py의 collect_newsroom(),
    services/llm.py의 filter_newsroom_articles(), compose_newsroom_message()를
    실제로 부른다(3단계는 이번 라운드에서 연다, docs/planning.md "뉴스룸" 절 12-3).
    🔴 2026-09-14 — SET-009 "지금 수집" 버튼이 같은 함수를 요청 스레드에서 직접
    불러 RunJob 전역 잠금을 거치지 않는 두 번째 진입점이었다(SET-001의 collect_now와
    같은 유형의 버그). 그 버튼을 철거해 지금은 이 축의 유일한 호출부다.
    🔴 4단계(Slack 발송)는 만들지 않기로 확정됐다(정책 12-0) — 미구현이 아니라
    결정이라 NOT_IMPLEMENTED_REASON을 쓰지 않는다(아래 jobs["newsroom_send"])."""
    from apps.newsroom.models import Newsroom, NewsroomArticle

    room = _target_newsroom()
    no_room_reason = (
        "" if room
        else "수집할 채널이 없어요" if not Newsroom.objects.filter(is_active=True).exists()
        else "활성 채널이 여러 개라 어느 채널인지 정할 수 없어요"
    )

    if room:
        has_work_ncollect = _job_has_work("newsroom_collect")
        run_display = _run_job_display("newsroom_collect", has_work_ncollect)
        if run_display:
            collect_job = run_display
        else:
            latest_article = NewsroomArticle.objects.filter(newsroom=room).order_by("-collected_at").first()
            state = "todo" if has_work_ncollect else "clear"
            collect_job = {
                "state": state, "state_label": STATE_LABELS[state],
                # CollectionLog는 본 파이프라인 전용이라 여기 쓰지 않는다(코디네이터 지시) —
                # 마지막 실행 요약은 NewsroomArticle.collected_at으로 만든다.
                "summary": (
                    f"마지막 수집 {timezone.localtime(latest_article.collected_at):%m/%d %H:%M}"
                    if latest_article else ""
                ),
            }
        collect_job.update({
            "can_run": True,
            "block_reason": "",
            "warning": "",
            "confirm_text": "",
            "run_url": reverse("setting_run_start", args=["newsroom_collect"]),
            "review_url": "",
        })
    else:
        collect_job = {
            "state": "clear", "state_label": STATE_LABELS["clear"], "summary": no_room_reason,
            "can_run": False, "block_reason": no_room_reason,
            "warning": "", "confirm_text": "", "run_url": "", "review_url": "",
        }

    jobs = {"newsroom_collect": collect_job}

    # 2단계 필터 — 이번 라운드에서 버튼을 연다(정책 12-2, 12-5 PE 인계 2~5번).
    # 🔴 휴먼 인 더 루프가 없어(12-2 (b)) GATED_JOB_KEYS에 넣지 않는다 — 완료
    # (STATUS_DONE)가 그대로 "완료"로 보여야지 "검토 대기"로 떨어지면 안 된다.
    # review_url도 비운다 — _run_node.html의 "결과 검토하기" 버튼 조건 둘(GATED
    # 여부·review_url 존재) 중 하나만 비워도 될 것을, 둘 다 비워 구조적으로 막는다.
    if room:
        pending_count = room.pending_count
        has_work_filter = pending_count > 0
        filter_display = _run_job_display("newsroom_filter", has_work_filter)
        filter_job = filter_display or {
            "state": "todo" if has_work_filter else "clear",
            "state_label": STATE_LABELS["todo" if has_work_filter else "clear"],
            "summary": "",
        }
        # 🔴 2026-09-16 PD 19차 개정 — 적체 줄(완료/전체)을 running만 빼고 항상
        # 내린다("제외 296건" 채널 누적 문제를 만들던 통과/제외 breakdown
        # summary는 걷었다 — 그 정보는 ROOM-002 목록이 이미 보여준다). summary는
        # 이제 _run_job_display()의 DONE 분기(아래 newsroom_filter 전용 갈래)가
        # RunJob.target_count/processed_count로 직접 만든다 — 채널 누적이 아니라
        # "그 실행 한 번이 무엇을 했나"를 말한다(PD 19차 ⑧번, 15차 규약 유지).
        # 🔴 2026-09-17 PD 25차 개정 — 할 일 수(pending_count)가 0이면
        # (_newsroom_filter_backlog()가 (None, None)을 반환하면) 흐름 줄도
        # 함께 내리지 않는다(cleanup·insight와 같은 근거). backlog가 있을
        # 때만 flow를 계산해 붙인다.
        if filter_job["state"] != "running":
            backlog, backlog_title = _newsroom_filter_backlog(room)
            if backlog:
                filter_job["backlog"], filter_job["backlog_title"] = backlog, backlog_title
                filter_job["flow"], filter_job["flow_title"] = _newsroom_filter_flow(room)
        # 🔴 PD 19차 개정 ⑧번 — clear 문구를 "판정할 기사가 없어요"(배지를
        # 되풀이)에서 "무엇이 열리는가"로 바꾼다. 채널에 기사가 아예 없으면
        # (1단계부터 필요) 종전 문구를 그대로 쓴다 — "3단계가 열린다"는 말이
        # 거짓이 되면 안 된다.
        if pending_count == 0 and room.articles.exists():
            filter_clear_reason = (
                "선별이 전부 끝났어요. 이 단계는 확정 없이 바로 반영돼서 "
                "3단계 브리핑 작성이 열려요"
            )
        else:
            filter_clear_reason = "선별할 기사가 없어요"
        filter_job.update({
            "can_run": pending_count > 0,
            "block_reason": "" if pending_count > 0 else filter_clear_reason,
            "warning": "",
            "confirm_text": "",
            "run_url": reverse("setting_run_start", args=["newsroom_filter"]) if pending_count > 0 else "",
            "review_url": "",
        })
    else:
        pending_count = 0
        filter_job = {
            "state": "clear", "state_label": STATE_LABELS["clear"], "summary": no_room_reason,
            "can_run": False, "block_reason": no_room_reason,
            "warning": "", "confirm_text": "", "run_url": "", "review_url": "",
        }
    jobs["newsroom_filter"] = filter_job

    # 3단계 발송문 — 이번 라운드에서 버튼을 연다(정책 12-3, 12-5 PE 인계 6~7번).
    # 🔴 휴먼 인 더 루프가 없다(12-3 (f) "3단계에 별도 확정 버튼을 두지 않는다" —
    # 사람이 끼어드는 자리가 이미 복사 행위 자체다) — GATED_JOB_KEYS에 넣지 않고
    # review_url도 비운다. 결과는 SET-009 발송 섹션(_newsroom_message.html)이
    # 보여준다 — 검토 화면이 따로 필요 없다.
    #
    # 🔴 2026-09-16 사용자 결정 — 날짜 축("오늘 발송문이 아직 없나")을 버린다.
    # 어제와 같은 재료로 같은 발송문을 또 만드는 일을 막는다 — 실제로 09/15
    # 16:24에 9건으로 발송문을 만들고 오늘도 passed가 그대로 9건인데(새 기사
    # 없음) 배지는 todo, 버튼도 열려 있던 실제 버그였다. 대신 "마지막 발송문
    # 이후 통과 기사가 늘었나"(_newsroom_compose_has_new_material())를 본다 —
    # _insight_has_new_material()과 같은 방식(새 재료 축)이다. pending_count
    # 선행 조건(2단계 미완이면 할 일 없음)은 그 함수 안에서 본다 — 여기서 다시
    # `pending_count == 0 and`로 검사하면 판정이 두 벌이 된다(2026-09-16 PM
    # 지적). 아래 pending_count는 has_work 판정이 아니라 block_reason 문구를
    # 만드는 데만 쓴다.
    if room:
        has_work_compose = _newsroom_compose_has_new_material(room)
        compose_display = _run_job_display("newsroom_compose", has_work_compose)
        compose_job = compose_display or {
            "state": "todo" if has_work_compose else "clear",
            "state_label": STATE_LABELS["todo" if has_work_compose else "clear"],
            "summary": "",
        }
        if pending_count > 0:
            # 🔴 아직 2단계를 안 돌렸거나 방금 수집한 기사가 판정 전으로 남아 있다
            # — "무엇을 하면 풀리는지"가 읽히도록 2단계 실행을 구체적으로 가리킨다.
            compose_job["block_reason"] = "선별 전 기사가 있어요. 2단계 기사 선별을 먼저 실행해 주세요"
            compose_can_run = False
        else:
            # 🔴 2026-09-16 사용자 결정 — state=='clear'(새 통과 기사 없음)면
            # can_run도 False다(배지와 버튼이 항상 같은 말을 한다).
            compose_can_run = _clear_can_run(compose_job, NEWSROOM_COMPOSE_CLEAR_BLOCK_REASON)
        compose_job.update({
            "can_run": compose_can_run,
            "block_reason": compose_job.get("block_reason", ""),
            "warning": "",
            "confirm_text": "",
            "run_url": reverse("setting_run_start", args=["newsroom_compose"]) if compose_can_run else "",
            "review_url": "",
        })
    else:
        compose_job = {
            "state": "clear", "state_label": STATE_LABELS["clear"], "summary": no_room_reason,
            "can_run": False, "block_reason": no_room_reason,
            "warning": "", "confirm_text": "", "run_url": "", "review_url": "",
        }
    jobs["newsroom_compose"] = compose_job

    # 4단계 발송 — 🔴 2026-09-16 22차 개정(design.md 22차 ④번, planning.md "뉴스룸"
    # 12-0 정정)으로 뜻이 뒤집혔다. 2026-09-15 지시("Slack 메시지는 구현하지마")는
    # 그 라운드의 범위 지정이었지 폐기 선언이 아니었다 — "안 만들기로 했다"가 아니라
    # "아직 안 만들었다"이므로 문구도 그 사실을 말한다. NOT_IMPLEMENTED_REASON을
    # 그대로 쓰지 않는 것은 이 자리 전용 문구(아래)가 "나중에 여기서 보낼 수
    # 있어요"까지 말해야 해서다.
    # 🔴 9번 노드는 "SET-010 노드 배지"(여섯 값) 표에 없다 — state는 "clear"(할
    # 일 없음 축)로 둬 idle이라는 죽은 값이 코드에 남지 않게 하되, 고유 라벨
    # ("준비 중")과 상태 값(clear)은 그대로 유지한다.
    jobs["newsroom_send"] = {
        "state": "clear",
        "state_label": "준비 중",
        "summary": "아직 만들지 않았어요. 나중에 여기서 보낼 수 있어요",
        "can_run": False,
        "block_reason": "Slack 발송은 아직 만들지 않았어요. 지금은 3단계 브리핑을 복사해서 직접 보내 주세요",
        "warning": "",
        "confirm_text": "",
        "run_url": "",
        "review_url": "",
    }

    # 🔴 15차 개정 ① — _research_jobs_context()와 같은 함수 하나로 네 노드를
    # 채운다(newsroom_send 포함, 항상 False — RunJob이 애초에 생기지 않는다).
    for key in jobs:
        jobs[key]["finished_today"] = _job_finished_today(key)
    return jobs


def setting_run(request):
    return render(request, "setting/run.html", {
        "setting_menu": _setting_menu("run"),
        **_run_graph_context(),
    })


def setting_run_graph(request):
    """폴링 대상 조각(3초). running_job이 있어야 _run_graph.html이 폴링 트리거를
    단다 — _current_running_job()이 RunJob을 실제로 읽으므로, 이제 이 뷰는 실행
    중일 때 3초마다 반복 호출된다."""
    return render(request, "setting/_run_graph.html", _run_graph_context())


@require_POST
def setting_run_start(request, job):
    if job not in RUN_JOB_KEYS:
        raise Http404
    if job == "collect":
        from services.runner import start_run
        start_run("collect", actor=RunJob.ACTOR_SCREEN)
    elif job == "newsroom_collect":
        room = _target_newsroom()
        if room:
            from services.runner import start_run
            start_run("newsroom_collect", actor=RunJob.ACTOR_SCREEN, newsroom_id=room.pk)
        # 대상 채널을 못 고르면(0개 또는 2개 이상) 조용히 아무 일도 하지 않는다 —
        # 노드 자체가 그 경우 can_run=False라 UI에서는 여기로 POST가 오지 않는다.
    elif job == "cleanup":
        from services.runner import start_run
        start_run("cleanup", actor=RunJob.ACTOR_SCREEN)
    elif job == "insight":
        # 🔴 2026-09-15 PE 개정 — 선행 잠금(_insight_block_reason())을 통과했을 때만
        # 노드가 run_url을 채워 여기로 POST를 보낸다. 화면이 아닌 경로로 직접 호출되면
        # 여기서는 다시 검사하지 않는다 — start_run() 자체가 대상 0건이어도 안전하게
        # 완료 처리하도록 이미 짜여 있다(services/runner.py _run_insight() "대상 0건").
        from services.runner import start_run
        start_run("insight", actor=RunJob.ACTOR_SCREEN)
    elif job == "weekly":
        # 🔴 같은 날 뒤이은 라운드 — 선행 잠금(_weekly_job_context())을 통과했을 때만
        # 노드가 run_url을 채운다. insight와 같은 이유로 여기서 다시 검사하지 않는다.
        from services.runner import start_run
        start_run("weekly", actor=RunJob.ACTOR_SCREEN)
    elif job == "monthly":
        from services.runner import start_run
        start_run("monthly", actor=RunJob.ACTOR_SCREEN)
    elif job == "newsroom_filter":
        # 🔴 이번 라운드 — 노드 자체가 판정 전 기사가 있을 때만(_newsroom_jobs_context()의
        # can_run = pending_count > 0) run_url을 채운다. newsroom_collect와 같은 이유로
        # 대상 채널을 다시 고른다 — 활성 채널이 0개나 2개 이상이면 그사이 바뀐 것이라
        # 조용히 아무 일도 하지 않는다.
        room = _target_newsroom()
        if room:
            from services.runner import start_run
            start_run("newsroom_filter", actor=RunJob.ACTOR_SCREEN, newsroom_id=room.pk)
    elif job == "newsroom_compose":
        # 🔴 이번 라운드 — 노드 자체가 통과 기사가 있을 때만
        # (_newsroom_jobs_context()의 compose_can_run) run_url을 채운다.
        # newsroom_filter와 같은 이유로 대상 채널을 다시 고른다.
        room = _target_newsroom()
        if room:
            from services.runner import start_run
            start_run("newsroom_compose", actor=RunJob.ACTOR_SCREEN, newsroom_id=room.pk)
    # 나머지 한 단계(뉴스룸 4단계 발송) — 만들지 않기로 확정됐다(정책 12-0).
    # 노드 자체가 run_url 없이 비활성이라 UI에서는 여기로 POST가 오지 않지만,
    # 직접 호출되더라도 그래프를 안전하게 다시 그려 준다.
    #
    # start_run()은 RunJob을 만들고 워커 스레드를 띄운 뒤 즉시 반환한다 — 여기서
    # 수집이 끝나기를 기다리지 않는다(gunicorn 요청 타임아웃에 걸리지 않는 이유,
    # docs/planning.md "실행 모델" 3-(d)). 이미 다른 작업이 진행중이면 start_run()이
    # None을 반환하고 아무것도 새로 만들지 않는다 — 아래 그래프 재렌더는 그 현재
    # 상태(진행중인 다른 작업)를 그대로 보여준다.
    return render(request, "setting/_run_graph.html", _run_graph_context())


@require_POST
def setting_run_stop(request, job):
    """SET-010 실행 중단 요청(docs/planning.md 「SET-010 실행 중단」, design.md 23차
    개정 ①). 🔴 「멈춰 달라」는 시각 하나만 RunJob에 적는다 — 상태(RunJob.status)는
    여기서 바꾸지 않는다. 상태를 바꾸는 것은 루프가 실제로 멈춘 뒤다
    (services/runner.py._execute()).

    🔴 job이 STOPPABLE_JOB_KEYS 셋이 아니면 그 노드에 중단 버튼 자체가 없어
    UI에서는 여기로 POST가 오지 않는다 — 직접 호출되면 404로 막는다(다섯 배치
    1호출 job은 애초에 멈출 자리가 없다).
    ⚠️ 지금 진행중인 RunJob이 이 job_key가 아니면(이미 끝났거나 다른 job이 도는
    중이면) 조용히 아무 일도 하지 않는다 — 옛 레코드를 건드리면 안 된다.
    ⚠️ stop_requested_at__isnull=True 조건을 걸어 두 번째 요청이 첫 번째 요청
    시각을 덮어쓰지 않게 한다(버튼이 한 번 누르면 즉시 잠기므로 정상 경로로는
    두 번째 요청이 오지 않지만, 방어적으로 멱등하게 둔다)."""
    if job not in STOPPABLE_JOB_KEYS:
        raise Http404
    RunJob.objects.filter(
        job_key=job, status=RunJob.STATUS_RUNNING, stop_requested_at__isnull=True,
    ).update(stop_requested_at=timezone.now())
    # 🔴 버튼이 hx-swap="outerHTML"로 이 응답을 그대로 갈아끼운다 — 다른 조각을
    # 돌려주면 화면이 통째로 어그러진다.
    return render(request, "setting/_run_graph.html", _run_graph_context())


BODY_PREVIEW_CHARS = 300


def _body_preview(body: str) -> str:
    """삭제 제안 행의 본문 미리보기. 전체 본문을 그대로 내려보내지 않는다 —
    run_review.html의 x-show 펼침 칸 하나에 쓰일 짧은 분량이면 충분하다."""
    if len(body) <= BODY_PREVIEW_CHARS:
        return body
    return body[:BODY_PREVIEW_CHARS] + "..."


def _dup_group_label(representative_news, member_count: int) -> str:
    """중복 보도 묶음 이름표(design.md "SET-010 · 실행" 28차 ①-2 실측 예시
    "DB손해보험 3건", "카카오 9건"). 대표 기사에 태깅된 첫 기업 이름 + 묶음 전체
    건수(대표 포함)를 쓴다. 태그가 없으면 이름을 지어내지 않고 "중복 보도"로
    떨어진다(「무조건 팩트 기반」) — 이 값은 DB로 넘어가는 보존 자산이 아니라
    화면 표시 전용이라 뷰가 매번 계산한다(dup_pick_reason과 같은 판단)."""
    org = representative_news.organizations.first()
    name = org.name if org else "중복 보도"
    return f"{name} {member_count}건"


def _format_duration(seconds: int) -> str:
    """review.step.duration 등에 쓰는 소요 시간 문자열. _run_job_display()의 elapsed
    포맷("1분 12초째")과 같은 자리수 규칙을 쓰되 접미사 "째"는 붙이지 않는다 — elapsed는
    "지금 몇 초째"(진행 중, 계속 갱신)를 말하고 이건 "다 걸린 시간"(완료, 고정값)을
    말해 뜻이 다르다."""
    return f"{seconds // 60}분 {seconds % 60}초" if seconds >= 60 else f"{seconds}초"


def _insight_items_context(run_jobs):
    """SET-010 3단계(주요 이슈) 검토 화면의 insight_items 목록. 계약은
    templates/setting/run_review.html 상단 주석 "insight_items" 절이 정본이다.

    🔴 2026-09-16 "SET-010 검토 단위" 절 — run_job 하나가 아니라 run_jobs 목록을
    받는다(_pending_review_run_jobs()가 만든 목록). 여러 배치의 확정 대기 초안이
    한 화면에 모인다.

    🔴 id는 RunDraft.pk다(News.pk가 아니다) — 확정 POST의 grade_<id>·insight_ids가
    이 값을 그대로 되돌려 보낸다.

    🔴 news_items의 url은 News.uid로 만든다(pk가 아니다) — NEWS-002의 URL 패턴이
    <shortuuid:uid>다(apps/news/urls.py). 3단계 입력은 이미 검증된 News라 실제로
    열린다(2단계 삭제 목록과 달리 404가 아니다, 템플릿 상단 계약 "근거 기사를 새 탭으로
    여는 이유")."""
    drafts = list(
        RunDraft.objects.filter(
            run_job__in=run_jobs, draft_type=RunDraft.TYPE_INSIGHT, status=RunProposal.STATUS_PENDING,
        ).prefetch_related("news").order_by("pk")
    )
    items = []
    for draft in drafts:
        news_list = list(draft.news.order_by("published_at"))
        news_range = ""
        if news_list:
            first_date = timezone.localtime(news_list[0].published_at).date()
            last_date = timezone.localtime(news_list[-1].published_at).date()
            news_range = (
                f"{first_date:%m.%d}" if first_date == last_date
                else f"{first_date:%m.%d} ~ {last_date:%m.%d}"
            )
        items.append({
            "id": draft.pk,
            "title": draft.title,
            "implication": draft.implication,
            "content": draft.content,
            "grade": draft.grade,
            "grade_reason": draft.grade_reason,
            "news_count": len(news_list),
            "news_range": news_range,
            "news_items": [
                {
                    "title": n.title, "published_at": n.published_at, "source": n.source_domain,
                    "url": reverse("news_detail", args=[n.uid]),
                }
                for n in news_list
            ],
        })
    return items


def _relation_items_context(run_jobs):
    """SET-010 3단계(주요 이슈) 검토 화면의 관계 초안 목록 — insight_items의 형제
    블록(docs/planning.md "지식그래프 관계 라벨링을 3단계의 두 번째 LLM 호출로
    옮긴다" 13번 PD 인계 1번 "insight_items 아래에 형제로 놓는다").

    🔴 PD 계약(templates/setting/run_review.html 1807~1814행, 2026-09-17 코디네이터
    실측 정정) — org_a/org_b는 문자열이 아니라 {name, org_type} 딕셔너리다.
    org_type으로 배지 색을 가른다(금융사/보험사/AI). 🔴 정렬도 PD가 못박았다 —
    "금융사·보험사가 org_a, AI가 org_b"다. RunDraft.relation_org_a/org_b는
    services/runner.py가 어느 순서로 채울지 아직 정해져 있지 않으므로(이번
    라운드는 그쪽을 건드리지 않는다), 이 함수가 매번 org_type으로 재정렬해
    화면 계약을 지킨다 — 모델 필드 순서에 기대지 않는다.

    🔴 id는 RunDraft.pk다(insight_items와 같은 계약) — 확정 POST의 relation_ids가
    이 값을 그대로 되돌려 보낸다. news_range는 insight_items와 같은 형태(발행일
    범위 "MM.DD ~ MM.DD" 또는 단일 "MM.DD")다.

    🔴 news_items의 url은 News.uid로 만든다(insight_items와 같은 이유 — 3단계
    입력은 이미 검증된 News라 실제로 열린다)."""
    drafts = list(
        RunDraft.objects.filter(
            run_job__in=run_jobs, draft_type=RunDraft.TYPE_RELATION, status=RunProposal.STATUS_PENDING,
        ).select_related("relation_org_a", "relation_org_b").prefetch_related("news").order_by("pk")
    )
    items = []
    for draft in drafts:
        news_list = list(draft.news.order_by("published_at"))
        news_range = ""
        if news_list:
            first_date = timezone.localtime(news_list[0].published_at).date()
            last_date = timezone.localtime(news_list[-1].published_at).date()
            news_range = (
                f"{first_date:%m.%d}" if first_date == last_date
                else f"{first_date:%m.%d} ~ {last_date:%m.%d}"
            )
        # 금융사/보험사를 org_a, AI를 org_b 자리에 놓는다(PD 계약). 모델의
        # relation_org_a/org_b는 순서를 보장하지 않으므로 org_type으로 가른다.
        org_pair = [draft.relation_org_a, draft.relation_org_b]
        org_a_obj = next((o for o in org_pair if o and o.org_type in ("금융사", "보험사")), None)
        org_b_obj = next((o for o in org_pair if o and o is not org_a_obj), None)

        def _org_dict(org):
            return {"name": org.name, "org_type": org.org_type} if org else {"name": "", "org_type": ""}

        items.append({
            "id": draft.pk,
            "title": draft.title,
            "org_a": _org_dict(org_a_obj),
            "org_b": _org_dict(org_b_obj),
            "label": draft.relation_label,
            "reason": draft.content,
            "news_count": len(news_list),
            "news_range": news_range,
            "news_items": [
                {
                    "title": n.title, "published_at": n.published_at, "source": n.source_domain,
                    "url": reverse("news_detail", args=[n.uid]),
                }
                for n in news_list
            ],
        })
    return items


def _report_items_context(run_jobs, job_key):
    """SET-010 4, 5단계(주간·월간 보고서) 검토 화면의 report_items 목록. 계약은
    templates/setting/run_review.html 상단 주석 "report_items" 절이 정본이다.

    🔴 2026-09-16 "SET-010 검토 단위" 절 — run_job 하나가 아니라 run_jobs 목록을
    받는다. job_key를 별도 인자로 받는 이유 — run_jobs가 비어 있을 수 없다는
    보장이 없어(호출부가 항상 비지 않은 목록만 넘기지만) run_jobs[0].job_key에
    기대지 않는다.

    🔴 주간과 월간이 이 한 함수를 같이 쓴다 — 갈리는 것은 draft_type 필터뿐이고
    그 값은 services/runner.py._run_report()가 이미 job_key별로 다르게 저장해
    뒀다. body_label만 job_key로 갈라 내린다(월간은 "주요 이슈 요약", REPORT-002가
    그렇게 부른다).

    🔴 id는 RunDraft.pk다 — 확정 POST의 draft_ids가 이 값을 그대로 되돌려 보낸다.
    🔴 grade/implication은 내리지 않는다 — 보고서 초안에는 그 두 칸이 없다(RunDraft
    docstring, "이슈 전용" 필드)."""
    drafts = list(
        RunDraft.objects.filter(
            run_job__in=run_jobs, draft_type__in=(RunDraft.TYPE_WEEKLY, RunDraft.TYPE_MONTHLY),
            status=RunProposal.STATUS_PENDING,
        ).prefetch_related("news").order_by("pk")
    )
    body_label = "주요 이슈 요약" if job_key == "monthly" else "주요 이슈"
    items = []
    for draft in drafts:
        news_list = list(draft.news.order_by("published_at"))
        items.append({
            "id": draft.pk,
            "title": draft.title,
            "overview": draft.overview,
            "content": draft.content,
            "body_label": body_label,
            "date_from": draft.date_from,
            "date_to": draft.date_to,
            "news_count": len(news_list),
            "news_items": [
                {
                    "title": n.title, "published_at": n.published_at, "source": n.source_domain,
                    "url": reverse("news_detail", args=[n.uid]),
                }
                for n in news_list
            ],
        })
    return items


# 🔴 2026-09-17 신설(docs/planning.md "검토 결과를 고도화 재료로 쓴다" 4-(가)) —
# 검토 화면 요약 ② 칸 맨 아래 한 줄이 읽는 값. "cleanup"만 뜻이 있다 — RunProposal에
# 거절 코드가 붙는 것이 삭제 제안뿐이고(위 RunProposal.reject_code docstring), 그
# 종류를 내는 job_key가 지금 "cleanup" 하나다(3단계는 문서 7번 "이번에 손대지
# 않는다", 4·5단계는 RunDraft라 애초에 대상이 아니다).
def _reject_stats_context(job_key):
    """지난 확정들의 거절·뒤집기 집계. 모수는 언제나 RunProposal 행 수다(docs/planning.md
    "검토 결과를 고도화 재료로 쓴다" 5번 — 화면의 "기사 N건"을 이 산식에 넣지 않는다).

    집계 범위는 이 job_key로 확정된 RunJob 전체다(같은 문서 "집계 범위는 뷰가
    정한다") — 월 단위로 자르지 않는다. 자르면 월 경계에 걸린 배치가 두 번 다른
    수로 보이고, 지금 규모(누적 이력 1,024건에 뒤집기 14건)에서는 전체를 보는
    것과 비용 차이가 없다.

    rejected와 reversed가 둘 다 0이면 None을 반환한다 — 호출부가 그러면 키
    자체를 내리지 않는다(줄째 사라지게 하는 것이 이 화면의 기존 규칙, 17차)."""
    confirmed_run_ids = list(
        RunJob.objects.filter(job_key=job_key, status=RunJob.STATUS_CONFIRMED).values_list("pk", flat=True)
    )
    if not confirmed_run_ids:
        return None

    proposals = RunProposal.objects.filter(run_job_id__in=confirmed_run_ids)
    rejected = proposals.filter(status=RunProposal.STATUS_REJECTED).count()
    reversed_count = proposals.filter(reversed_at__isnull=False).count()
    if not rejected and not reversed_count:
        return None

    # 🔴 빈 문자열(이 칸을 만들기 전에 거절된 과거 행)도 "미기입"으로 묶는다 —
    # 확정 뷰가 이번 라운드부터는 항상 "미기입"을 명시적으로 쓰지만, 마이그레이션
    # 이전 행은 기본값 그대로 빈 문자열이다.
    code_counts = Counter(
        code or RunProposal.REJECT_CODE_UNSPECIFIED
        for code in proposals.filter(status=RunProposal.STATUS_REJECTED).values_list("reject_code", flat=True)
    )
    codes = [
        {"label": label, "count": count}
        for label, count in sorted(code_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "runs": len(confirmed_run_ids),
        "rejected": rejected,
        "reversed": reversed_count,
        "codes": codes,
    }


def _run_review_context(job_key):
    """SET-010 검토 화면(run_review.html)의 review dict를 만든다. 계약은
    templates/setting/run_review.html 상단 주석과 docs/design.md "4차 개정" ⑩번 표가
    정본이다.

    🔴 검증 게이트 네 번째 예외(apps/news/models.py NewsQuerySet.verified() docstring
    (D))가 적용되는 자리다 — RunProposal이 참조하는 News는 아직 미검증이라
    News.objects.verified()를 거치지 않고, RunProposal을 통해서만(select_related)
    조회한다. NEWS-001/002, ALL-001, GRAPH-001의 어떤 집계에도 여기서 조회한 News가
    섞이지 않는다(그 화면들은 이 함수를 전혀 호출하지 않는다)."""
    review = {
        "job_label": RUN_JOB_LABELS[job_key],
        "back_url": reverse("setting_run"),
        "confirm_url": reverse("setting_run_review_confirm", args=[job_key]),
        # 🔴 2026-09-15 PE 개정 — setting_run_review_cancel이 이제 실제로 취소한다(아래
        # 뷰 참고). 3단계(주요 이슈)는 이 URL이 반드시 있어야 한다 — 초안 0건으로 끝난
        # 배치(묶을 이슈가 없는 날)는 확정 버튼이 채택할 것이 없어 잠기고, cancel_url까지
        # 비면 그 RunJob이 검토 대기에서 나올 길이 화면에 하나도 없다(템플릿 상단 계약
        # "3단계에서 cancel_url을 반드시 채운다").
        "cancel_url": reverse("setting_run_review_cancel", args=[job_key]),
        "org_admin_url": reverse("setting_organizations"),
        # 🔴 2026-09-15 신설 — 태그 후보가 기업 전용에서 기업/기술 주제 축 일반화로
        # 바뀌면서(docs/planning.md 4-(b) 개정) 기술 주제 후보도 등록 화면 링크가
        # 필요해졌다. SET-008(기술 주제 관리)로 보낸다.
        "topic_admin_url": reverse("setting_tech_topics"),
        "criterion_legend": CRITERION_LEGEND,
        # 🔴 2026-09-16 23차 개정(design.md 23차 ③) — 태그 후보(기업 축) 등록 줄의
        # 유형 선택지. SET-007과 같은 출처(Organization.ORG_TYPE_CHOICES)를 그대로
        # 써야 두 화면이 같은 목록을 본다.
        "org_types": Organization.ORG_TYPE_CHOICES,
    }

    # 🔴 2026-09-16 "SET-010 검토 단위" 절 확정 — 「가장 최근 RunJob 하나」가
    # 아니라 확정 대기 제안(또는 초안)이 있는 배치 전부를 본다. 배치가 여럿이어도
    # 한 화면에 모인다(오늘 사고 — pk107·pk108·pk130 세 배치의 335건 중 233건이
    # 화면에서 사라졌던 원인이 정확히 "최신 하나만 본다"였다).
    run_jobs = _pending_review_run_jobs(job_key)
    if not run_jobs:
        return review

    representative = run_jobs[-1]
    state, state_label = _job_run_state(representative, job_key, _job_has_work(job_key))
    # 🔴 PD 19차 개정 ⑤번 — 머리글은 작업 이름과 배지만 말한다. 실행 시각과
    # 진행률(review.run.label/progress/failed_str/resumable)은 "배치의 것"이라
    # 내렸다 — 여러 배치가 한 화면에 모이면 "그 실행"이라는 단수가 성립하지
    # 않는다. 화면(run_review.html)은 review.run.state/state_label만 쓴다.
    review["run"] = {"state": state, "state_label": state_label}

    is_draft_based = job_key in ("insight", "weekly", "monthly")
    if is_draft_based:
        # 🔴 2026-09-17 개정 — job_key=="insight"는 이제 draft_type 둘(이슈·관계)을
        # 함께 본다(3단계 두 번째 호출의 산출물이 관계 초안이다, RunDraft docstring).
        # 이 목록(pending_drafts)은 아래 "① 검토 대상" 집계(review.input)와
        # review["cancel_count"]가 함께 쓰므로, 화면에 새로 뜨는 관계 블록 몫도
        # "지금 대기 중인 것"에 반영된다 — insight_items/relation_items는 이 아래
        # 별도 조회로 각자 센다(섞이지 않는다).
        draft_filter = (
            {"draft_type__in": (RunDraft.TYPE_INSIGHT, RunDraft.TYPE_RELATION)} if job_key == "insight"
            else {"draft_type__in": (RunDraft.TYPE_WEEKLY, RunDraft.TYPE_MONTHLY)}
        )
        pending_drafts = list(
            RunDraft.objects.filter(
                run_job__in=run_jobs, status=RunProposal.STATUS_PENDING, **draft_filter,
            ).prefetch_related("news")
        )
        proposals = []
    else:
        proposals = list(
            RunProposal.objects.filter(run_job__in=run_jobs, status=RunProposal.STATUS_PENDING)
            .select_related("news", "duplicate_representative")
            .order_by("-news__published_at", "news_id", "pk")
        )
        pending_drafts = []

    # 🔴 PD 19차 개정 ⑤번 "① 검토 대상" — 기사 수(count) / 제안 수(proposal_count,
    # 신설) / 가장 오래 기다린 날(since, 신설, "MM/DD"). 사용자가 물은 것이
    # 정확히 "기사 수"였고, 기사 67건에 제안 161건처럼 둘이 크게 갈릴 수 있어
    # 나눠 보여준다.
    review["input"] = {}
    if job_key in REVIEW_INPUT_LABEL_BY_JOB:
        if is_draft_based:
            news_ids = set()
            for draft in pending_drafts:
                news_ids.update(n.pk for n in draft.news.all())
            review["input"] = {
                "count": len(news_ids),
                "proposal_count": len(pending_drafts),
                "label": REVIEW_INPUT_LABEL_BY_JOB[job_key],
            }
        else:
            news_dates = [
                timezone.localtime(p.news.collected_at).date() for p in proposals if p.news_id
            ]
            review["input"] = {
                "count": len({p.news_id for p in proposals if p.news_id}),
                "proposal_count": len(proposals),
                "label": REVIEW_INPUT_LABEL_BY_JOB[job_key],
                "since": f"{min(news_dates):%m/%d}" if news_dates else "",
            }

    # 🔴 PD 19차 개정 ⑤번 "② AI가 한 일" — 실행 횟수(run_count, 맨 앞 조각 —
    # 뒤 셋의 모수를 정해 준다)·모델·합계 시간·합계 토큰. 토큰과 시간은 이제
    # "그 배치의 값"이 아니라 여러 배치의 합계다(여러 번의 실행에서 모였다는
    # 사실 자체가 이번 사고를 화면이 스스로 말하는 자리).
    step = {"prompt_version": representative.prompt_version}
    if job_key in REVIEW_STEP_SUMMARY_BY_JOB:
        step["summary"] = REVIEW_STEP_SUMMARY_BY_JOB[job_key]
        # 🔴 모델 이름은 RunJob에 배치별로 저장돼 있지 않다(설정값을 그때그때
        # 읽어 쓸 뿐 어떤 모델이 실제로 돌았는지는 기록하지 않는다) — 그래서
        # "갈리면 모델 2가지" 판정은 이번 라운드에서 구현하지 않는다. 지금
        # 설정값을 그대로 보여준다(설정이 배치 사이에 바뀌지 않은 한 정확하다).
        model_setting_key = REVIEW_MODEL_KEY_BY_JOB.get(job_key, "ANTHROPIC_MODEL_FAST")
        step["model"] = getattr(settings, model_setting_key)
        if len(run_jobs) > 1:
            step["run_count"] = len(run_jobs)
        prompt_versions = {rj.prompt_version for rj in run_jobs if rj.prompt_version}
        # 🔴 2026-09-16 — 기존 슬롯(step["notice"])을 그대로 재사용한다(design.md
        # "SET-010 · 실행" 21차 개정 ⑧번 "새 자리를 만들지 않은 것이 판단이다"). 두
        # 종류(기준 갈림 / 사전 차단 규칙 회귀 반례)가 겹치면 한 줄에 이어 쓴다 —
        # 줄을 둘로 늘리면 요약 칸 세 개의 높이가 어긋난다.
        notices = []
        if len(prompt_versions) > 1:
            notices.append("판정 기준이 다른 실행이 섞여 있어요")
        if job_key == "cleanup":
            # 🔴 "다음에 이 화면을 열 때" 보이는 자리 — 가장 최근에 확정된 cleanup
            # RunJob의 regression_flag_count를 읽는다(확정 뷰가 채운 값). messages.warning은
            # 확정 직후 한 번 뜨고 사라지지만, 낱말 목록을 넓히는 일은 코드를 고쳐야
            # 해서 사용자가 그 자리에서 처리할 수 없어 여기서도 보여야 한다.
            last_regression = (
                RunJob.objects.filter(
                    job_key="cleanup", status=RunJob.STATUS_CONFIRMED, regression_flag_count__gt=0,
                ).order_by("-confirmed_at", "-pk").first()
            )
            if last_regression:
                notices.append(
                    f"지난 확정에서 규칙으로 걸러질 뻔한 기사가 "
                    f"{last_regression.regression_flag_count}건 나왔어요. 낱말 목록을 넓혀야 해요."
                )
        if notices:
            step["notice"] = " ".join(notices)
        total_seconds = sum(
            (rj.finished_at - rj.started_at).total_seconds()
            for rj in run_jobs if rj.started_at and rj.finished_at
        )
        if total_seconds:
            step["duration"] = _format_duration(int(total_seconds))
        total_tokens = sum(
            rj.input_tokens + rj.output_tokens
            + rj.cache_creation_input_tokens + rj.cache_read_input_tokens
            for rj in run_jobs
        )
        if total_tokens:
            step["tokens"] = f"{total_tokens:,}"
    review["step"] = step

    # 🔴 2026-09-17 신설(docs/planning.md "검토 결과를 고도화 재료로 쓴다" 4-(가)) —
    # "cleanup"만 뜻이 있다(위 _reject_stats_context() docstring 참고). 둘 다 0이면
    # None이 와 review에 키를 만들지 않는다 — 화면이 그 줄을 통째로 접는다.
    if job_key == "cleanup":
        reject_stats = _reject_stats_context(job_key)
        if reject_stats:
            review["reject_stats"] = reject_stats

    # 태그 제안의 target_type(기업 배지 색) 조회 — 제안마다 쿼리하지 않게 한 번에 모은다.
    org_type_by_name = dict(Organization.objects.values_list("name", "org_type"))

    delete_items = []
    retag_by_news = {}  # news_id 순서 보존(dict, 3.7+) — "같은 기사 행이 흩어지지 않게"
    tag_candidates = []
    # 🔴 2026-09-17 28차 정정 신설(docs/design.md "SET-010 · 실행" 28차 정정) — 중복
    # 보도(TYPE_DUPLICATE) 제안을 대표 News.pk로 묶는다. dict 키 순서 보존(3.7+)으로
    # published_at 내림차순 정렬(위 쿼리)이 그대로 유지된다 — 각 묶음의 첫 등장
    # 순서가 그 묶음의 위치가 된다.
    dup_by_rep = {}
    keep_count = 0
    delete_news_ids = set()

    for p in proposals:
        if p.proposal_type == RunProposal.TYPE_DELETE:
            delete_news_ids.add(p.news_id)
            # 🔴 2026-09-16 — 판정 주체가 둘이 됐다(docs/design.md "SET-010 · 실행"
            # 21차 개정). by_rule=True는 LLM을 부르지 않고 코드 사전 차단 규칙
            # (services/cleanup_prefilter.py)이 낸 제안이다. criterion_code/
            # criterion_label은 코드 행에서 빈 문자열로 내린다 — 기준 코드는 LLM
            # 판정 어휘라 규칙 판정에 붙으면 두 주체의 정확도가 한 통계에 섞인다
            # (정책 4-3, 21차 ⑦번).
            by_rule = p.judged_by == RunProposal.JUDGED_BY_CODE_AI_KEYWORD_RULE
            delete_items.append({
                "id": p.pk,
                "title": p.news.title,
                "published_at": p.news.published_at,
                "source": p.news.source_domain,
                # 🔴 2026-09-17 26차 신설(design.md ①-7) — 원문 링크. News.url 그대로다.
                "url": p.news.url,
                "body_preview": _body_preview(p.news.body),
                "by_rule": by_rule,
                "criterion_code": "" if by_rule else p.criterion_code,
                "criterion_label": "" if by_rule else CRITERION_LABELS.get(p.criterion_code, ""),
                "reason": p.reason,
            })
        elif p.proposal_type == RunProposal.TYPE_KEEP:
            keep_count += 1
        elif p.proposal_type in (RunProposal.TYPE_TAG_ADD, RunProposal.TYPE_TAG_REMOVE):
            group = retag_by_news.get(p.news_id)
            if group is None:
                group = {
                    "title": p.news.title,
                    "published_at": p.news.published_at,
                    "source": p.news.source_domain,
                    # 🔴 2026-09-17 26차 신설(design.md ①-7) — group에 붙는다. items에는
                    # 붙이지 않는다(원문은 기사의 것이지 제안의 것이 아니다, ①-4).
                    "url": p.news.url,
                    "has_delete_proposal": False,
                    "items": [],
                }
                retag_by_news[p.news_id] = group
            group["items"].append({
                "id": p.pk,
                "action": "add" if p.proposal_type == RunProposal.TYPE_TAG_ADD else "remove",
                "action_label": "태그 추가" if p.proposal_type == RunProposal.TYPE_TAG_ADD else "태그 제거",
                "axis": p.axis,
                "axis_label": dict(TagCorrectionRecord.AXIS_CHOICES).get(p.axis, p.axis),
                "target_name": p.target_name,
                "target_type": org_type_by_name.get(p.target_name, "") if p.axis == TagCorrectionRecord.AXIS_ORGANIZATION else "",
                "reason": p.reason,
            })
        elif p.proposal_type == RunProposal.TYPE_TAG_CANDIDATE:
            # 🔴 2026-09-15 개정(docs/planning.md 4-(b)) — 기업 전용이던 후보를 축
            # 일반화했다. axis_label로 화면에서 기업/기술 주제를 갈라 보여주고,
            # admin_url을 축별로 다르게 둬(SET-007/SET-008) 템플릿이 분기 없이 바로
            # 링크를 쓸 수 있게 한다.
            tag_candidates.append({
                "name": p.target_name,
                "axis": p.axis,
                "axis_label": dict(TagCorrectionRecord.AXIS_CHOICES).get(p.axis, p.axis),
                "admin_url": (
                    review["org_admin_url"] if p.axis == TagCorrectionRecord.AXIS_ORGANIZATION
                    else review["topic_admin_url"]
                ),
                "reason": p.reason,
                "title": p.news.title,
                "published_at": p.news.published_at,
                "source": p.news.source_domain,
                # 🔴 2026-09-17 26차 신설(design.md ①-7) — 후보가 나온 기사의 원문 링크.
                "url": p.news.url,
                # 🔴 2026-09-16 23차 개정(design.md 23차 ③) — 인라인 등록 컨트롤이
                # 쓰는 두 값. proposal_id는 한 화면에서 유일해야 한다(RunProposal.pk라
                # 보장된다). register_url이 비면(있을 수 없지만) 그 줄의 등록 자리만
                # 사라진다.
                "proposal_id": p.pk,
                "register_url": reverse("setting_run_tag_candidate_register", args=[p.pk]),
            })
        elif p.proposal_type == RunProposal.TYPE_DUPLICATE:
            # 🔴 2026-09-17 28차 정정(docs/design.md "SET-010 · 실행" 28차 정정) —
            # 삭제가 아니라 감추기다. 이 행은 삭제 제안 카드(delete_items)에 절대
            # 섞이지 않는다 — proposal_type이 TYPE_DELETE와 다른 값이라 위
            # `if p.proposal_type == RunProposal.TYPE_DELETE:` 분기를 애초에 타지
            # 않는다(⚠️ "delete_items에서 중복 행을 제외한다"는 요구가 이 분기 구조
            # 자체로 충족된다).
            #
            # 대표에는 RunProposal 행이 없다(모델 docstring 참고) — 그래서 대표
            # 정보(title/published_at/source/url/pick_reason)는 p.duplicate_representative
            # (News, select_related로 이미 가져와 있다)에서 얻는다. 보류(hold) 묶음은
            # 이번 라운드에서 RunProposal 자체를 만들지 않으므로(services/runner.py가
            # 아직 그 경로를 배선하지 않았다 — "다음 라운드" 몫, services/dedup_candidates.py
            # 독스트링 참고) 여기서 만드는 묶음은 전부 hold=False다.
            rep_id = p.duplicate_representative_id
            group = dup_by_rep.get(rep_id)
            if group is None:
                group = {"representative_news": p.duplicate_representative, "items": []}
                dup_by_rep[rep_id] = group
            group["items"].append({
                "id": p.pk,
                "title": p.news.title,
                "published_at": p.news.published_at,
                "source": p.news.source_domain,
                "url": p.news.url,
                "reason": p.reason,
                # 🔴 Insight.news/Report.news/OrgRelation.news 역참조 수(design.md
                # ⑩-1) — 감출 행에 이 배지가 뜨면 그 자체가 규칙 위반 신호다(대표
                # 선정이 "명시 연결 있는 것 우선"이라 정상적으로는 0이어야 한다).
                "insight_count": p.news.insights.count(),
                "report_count": p.news.reports.count(),
                "relation_count": p.news.org_relations.count(),
            })
            # 같은 묶음의 모든 행이 같은 값을 갖는다(모델 필드 docstring 참고) — 마지막에
            # 본 행 값으로 채워도 결과가 같지만, 매번 그대로 덮어써 둔다.
            group["fingerprint"] = p.dup_fingerprint
            group["pick_reason"] = p.dup_pick_reason

    for news_id, group in retag_by_news.items():
        group["has_delete_proposal"] = news_id in delete_news_ids

    retag_groups = list(retag_by_news.values())

    # 🔴 2026-09-17 28차 정정 — dup_by_rep(대표 pk별로 모은 dict)를 화면 계약
    # (docs/design.md 28차 개정 ⑩-1)이 요구하는 review.dup_groups 형태로 바꾼다.
    # 🔴 "보류(hold=True)" 갈래는 이번 라운드에 만들지 않는다 — 그 갈래는 애초에
    # RunProposal이 생기지 않는 경우라(모델 필드 docstring, design.md 28차 ④-1
    # "RunProposal 자체가 만들어지지 않았다") 여기서 조립할 데이터 원천이 없다.
    # 그래서 dup_hold_count는 항상 0이고, "대기 중인 중복 제안이 없으면 0건이
    # 정상"인 지금 상태와 화면이 27차와 한 픽셀도 다르지 않다.
    dup_groups = []
    for group in dup_by_rep.values():
        rep_news = group["representative_news"]
        items = group["items"]
        if not items:
            continue
        dup_groups.append({
            "hold": False,
            "label": _dup_group_label(rep_news, len(items) + 1) if rep_news else "",
            "fingerprint": group["fingerprint"],
            "representative": {
                "title": rep_news.title,
                "published_at": rep_news.published_at,
                "source": rep_news.source_domain,
                "url": rep_news.url,
                "pick_reason": group["pick_reason"],
            } if rep_news else None,
            "items": items,
        })
    # 🔴 정렬 — hold=True 묶음이 앞에 모여야 한다(design.md ⑩-1). 지금은 hold=True가
    # 생기지 않지만, 뷰가 정렬을 맡는다는 계약을 미리 지켜 둔다 — 나중에 hold 갈래가
    # 생겨도 이 자리를 다시 고칠 필요가 없다. sort()는 stable이라 dup_by_rep 삽입
    # 순서(News.published_at 내림차순, 위 쿼리)가 hold 값이 같은 묶음끼리는 그대로
    # 보존된다.
    dup_groups.sort(key=lambda g: not g["hold"])
    dup_hide_count = sum(len(g["items"]) for g in dup_groups if not g["hold"])
    dup_hold_count = sum(len(g["items"]) for g in dup_groups if g["hold"])

    # 🔴 2026-09-16 — 코드 규칙 제안(by_rule=True)을 앞에 모은다(design.md 21차 개정
    # ⑤번). 반증("이건 남았어야 했다")이 코드 그룹 안에 모여 있어야 발견되고, 5건뿐인
    # 코드 그룹을 뒤에 두면 86건짜리 LLM 그룹에 묻혀 실질적으로 안 보인다. 템플릿은
    # 정렬하지 않는다(21차 ⑤번) — sort()는 stable이라 같은 by_rule 안에서는 기존
    # published_at 내림차순이 그대로 보존된다.
    delete_items.sort(key=lambda item: not item["by_rule"])
    rule_delete_count = sum(1 for item in delete_items if item["by_rule"])
    llm_delete_count = len(delete_items) - rule_delete_count

    review["delete_items"] = delete_items
    review["retag_groups"] = retag_groups
    # 🔴 2026-09-15 개정 — org_candidates에서 tag_candidates로 이름을 바꿨다(축 일반화).
    # 화면 쪽(templates/setting/run_review.html)도 함께 바뀌어야 한다 — PD 인계 사항.
    review["tag_candidates"] = tag_candidates
    # 🔴 2026-09-17 28차 정정 신설 — 빈 리스트여도 그대로 내린다. 템플릿의
    # `{% if review.dup_groups %}`가 빈 리스트를 거짓으로 보므로 카드가 조용히
    # 사라진다(대기 중인 중복 제안이 없는 평소 상태와 같은 렌더 결과).
    review["dup_groups"] = dup_groups

    # 🔴 2026-09-15 PE 신설 — 3단계(주요 이슈) 초안. RunProposal이 아니라 RunDraft에서
    # 온다(설계 3번 "산출물의 모양이 다르다"). insight_count는 None과 0을 구분해 내린다
    # — job_key가 "insight"가 아니면 아예 키를 만들지 않아 템플릿이 기존 정리 작업용
    # 문구(삭제·태그 교정·유지)로 떨어지고, "insight"인데 초안이 0건이면 정확히 0을
    # 내려 "새로 쓴 이슈 초안 0건"이 찍히게 한다.
    output = {
        "delete_count": len(delete_items),
        # 🔴 2026-09-16 신설(design.md 21차 개정 ⑨번) — 뷰가 직접 뺄셈해 내린다(Django
        # 템플릿에 뺄셈이 없다). 둘의 합은 항상 delete_count와 같다.
        "rule_delete_count": rule_delete_count,
        "llm_delete_count": llm_delete_count,
        # 🔴 2026-09-17 버그 수정 — has_delete_proposal인 그룹은 뺀다. 확정 뷰가
        # 삭제부터 처리한 뒤 "그 기사가 이번에 삭제됐으면 태그 제안은 취소로
        # 남긴다"(News.delete()의 on_delete=SET_NULL과 별개로, 아래 확정 뷰가
        # news_id in deleted_news_ids로 직접 판단)를 실행하므로, 같은 기사에
        # 삭제와 태그 교정이 함께 걸려 있으면 그 태그 교정은 실제로는 절대
        # 채택되지 않는다. 여기서 빼지 않으면 이 숫자가 "확정을 누르면 실제로
        # 반영될 건수"가 아니라 "지금 대기 중인 제안 수"가 되어, 확정 버튼
        # 라벨과 실제 채택 결과가 어긋난다(실측: RunJob pk186 — 태그 제거
        # 129건 중 105건이 삭제와 겹쳐 취소됨, 라벨은 130건 그대로 표시).
        "retag_count": sum(len(g["items"]) for g in retag_groups if not g["has_delete_proposal"]),
        # 🔴 2026-09-17 27차 신설(design.md 27차 개정) — 카드 머리 숫자는 이제 대기
        # 태그 제안 행 수 전량(retag_total_count)을 쓴다. 확정 시 반영될 행 수만
        # 보이던 종전 retag_count는 나열된 130행과 어긋났다(실측: RunJob pk186).
        # retag_canceled_count는 그 차이(has_delete_proposal 그룹의 행 수 합)를
        # 뷰가 직접 더해 내린다 — 템플릿에서 뺄셈하지 않는다(21차 llm_delete_count와
        # 같은 근거). total = count + canceled가 항상 맞는다.
        "retag_total_count": sum(len(g["items"]) for g in retag_groups),
        "retag_canceled_count": sum(len(g["items"]) for g in retag_groups if g["has_delete_proposal"]),
        # 🔴 2026-09-17 28차 정정 신설(docs/design.md "SET-010 · 실행" 28차 정정 ④번) —
        # 중복 보도 카드가 쓰는 건수 셋. dup_hide_count + dup_hold_count = dup_row_count가
        # 화면 안에서 검산된다(뷰가 보장한다 — 템플릿에서 더하지 않는다).
        # ⚠️ delete_count(위)는 이미 TYPE_DUPLICATE 행을 포함하지 않는다 —
        # delete_items가 proposal_type == TYPE_DELETE인 행만 모으므로(다른 elif
        # 분기), "중복분 제외"라는 28차 정정 계약이 타입을 가른 시점에 이미 충족된다.
        "dup_hide_count": dup_hide_count,
        "dup_hold_count": dup_hold_count,
        "dup_row_count": dup_hide_count + dup_hold_count,
        "keep_count": keep_count,
        # 🔴 커버리지·잠금 조건에 세지 않는다(run_review.html 상단 계약, design.md 4차
        # 개정 ⑩번) — OUTPUT 칸에만 별도로 찍는다. 이제 기업 후보뿐 아니라 기술 주제
        # 후보도 합산한 개수다.
        "candidate_count": len(tag_candidates),
        # 🔴 2026-09-16 "SET-010 검토 단위" 절 확정 — 커버리지 조건(uncovered_count의
        # 배치 산술)이 통째로 없어졌다. 검토 화면이 열렸다는 것 자체가 이제 B(미판정)가
        # 0이라는 뜻이라(cleanup) — "판정 안 된 기사가 조용히 검증됨으로 넘어가는 것"은
        # 화면에 들어오기 전에 이미 막힌다. 값 자체는 마지막 안전망으로 0을 그대로
        # 남겨 둔다(design.md 19차 개정 ④번 — "검토 화면의 uncoveredCount 잠금은
        # 남겨 뒀다").
        "uncovered_count": 0,
    }
    if job_key == "insight":
        insight_items = _insight_items_context(run_jobs)
        review["insight_items"] = insight_items
        output["insight_count"] = len(insight_items)
        output["draft_noun"] = RunDraft.TYPE_INSIGHT
        # 🔴 2026-09-17 신설 — 관계 초안(형제 블록, 13번 PD 인계 1·3번). 대기 중인
        # 관계 제안이 없으면 relation_items는 빈 리스트, relation_count는 0이다
        # (아직 서비스 쪽 생성 경로가 배선되지 않은 지금은 항상 0이 정상).
        relation_items = _relation_items_context(run_jobs)
        review["relation_items"] = relation_items
        output["relation_count"] = len(relation_items)
    elif job_key in ("weekly", "monthly"):
        # 🔴 같은 날 뒤이은 라운드 — 4, 5단계 보고서 초안. insight와 같은 이유로
        # RunProposal이 아니라 RunDraft에서 온다. insight_count 키를 그대로 쓰는 이유는
        # run_review.html 상단 계약 "output.insight_count" 주석 참고 — "세는 것이
        # '채택 대상 RunDraft 수'로 같아서 키를 늘리지 않았다."
        report_items = _report_items_context(run_jobs, job_key)
        review["report_items"] = report_items
        output["insight_count"] = len(report_items)
        output["draft_noun"] = RunDraft.TYPE_WEEKLY if job_key == "weekly" else RunDraft.TYPE_MONTHLY
    review["output"] = output

    # 🔴 2026-09-16 신설(design.md 21차 개정 ⑨번) — 코드 그룹 머리의 title에만 쓰는
    # 선택 값. 코드 제안이 0건이면 그룹 머리 자체가 안 그려지므로 만들지 않는다.
    # 낱말 목록은 services/cleanup_prefilter.AI_KEYWORDS 한 곳(정책 8번)에서 그대로
    # 가져온다 — 여기서 다시 쓰면 그 목록과 갈릴 수 있다.
    if rule_delete_count:
        review["rule_words"] = ", ".join(AI_KEYWORDS)

    # 🔴 PD 19차 개정 ⑥번 신설 — "모두 취소"가 버릴 대기 제안(또는 초안) 수.
    # 화면이 보여주는 범위와 글자 그대로 같다(체크 상태와 무관하게 서버 값
    # 그대로다).
    review["cancel_count"] = len(proposals) if proposals else len(pending_drafts)
    return review


# 🔴 2026-09-15 PE 신설 — job_key별 grade_choices. run_review.html 계약이 "미지정"을
# 빼라고 요구한다(그대로 내리면 브라우저가 select의 첫 option을 고르므로 미지정 Insight가
# 아무도 안 누른 채 만들어진다). Insight.GRADE_CHOICES를 그대로 참조해 드리프트를 막되
# GRADE_UNSPECIFIED 한 항목만 걸러 낸다. 4, 5단계(보고서)는 등급이 없으므로 빈 채로
# 둔다(이번 라운드 범위 밖, RESEARCH_JOB_KEYS 중 "insight"만 채운다).
GRADE_CHOICES_BY_JOB = {
    "insight": [c for c in Insight.GRADE_CHOICES if c[0] != Insight.GRADE_UNSPECIFIED],
}


def setting_run_review(request, job):
    """SET-010 검토 화면(휴먼 인 더 루프). 계약은 templates/setting/run_review.html 상단
    주석이 정본이다. 실제 컨텍스트는 _run_review_context()가 만든다 — 대상 job_key로
    RunJob이 한 번도 없었으면 job_label/back_url 등 URL류만 채우고 나머지는 빈 상태로
    정상 렌더된다(그 함수 안에서 처리)."""
    if job not in RUN_JOB_KEYS:
        raise Http404
    return render(request, "setting/run_review.html", {
        "setting_menu": _setting_menu("run"),
        "review": _run_review_context(job),
        "grade_choices": GRADE_CHOICES_BY_JOB.get(job, []),
    })


def _confirm_insight_drafts(request, run_jobs) -> None:
    """SET-010 3단계(주요 이슈) 확정. 채택된 RunDraft마다 Insight를 만들어 근거
    News를 M2M으로 옮기고, 등급은 사람이 고른 값을 그대로 쓴다(설계 6번 표). 거절된
    초안은 지우지 않고 상태만 남긴다 — 거절 분포가 프롬프트 정확도를 잴 정답지라는
    원칙이 2단계와 같다.

    🔴 2026-09-16 "SET-010 검토 단위" 절 — run_job 하나가 아니라 run_jobs 목록을
    받는다. 여러 배치를 한 번에 확정할 수 있다.

    🔴 2026-09-16 같은 절 11번 — 3단계 탈락 표식. 각 run_job이 얼려 둔
    insight_candidates(그 배치가 후보로 고려한 News 전부, services/runner.py
    _run_insight())에서 이번 확정으로 실제 채택된 Insight의 news를 뺀 나머지에
    News.insight_dismissed_at을 찍는다 — 「이슈로 묶이지 않은 대상은 다음 3단계
    실행에서 대상에서 빠진다」는 새 설계(대상 = 탈락 표식 없는 미배정 전체)의
    전제다. 표식이 없으면 같은 기준으로 반복 탈락하는 기사가 실행마다 다시
    대상이 되어 3단계가 영구히 "할 일 있음"이 된다.

    🔴 축약본(content_short/implication_short)은 비워 둔다 — RA가 채운다(모델
    default가 이미 빈 문자열이라 여기서 따로 손대지 않는다).
    🔴 headliner_order도 건드리지 않는다 — RA가 배치 단위로 전량 교체한다."""
    accepted_ids = set(request.POST.getlist("insight_ids"))
    candidate_ids = set()
    assigned_ids = set()
    for run_job in run_jobs:
        candidate_ids.update(run_job.insight_candidates.values_list("pk", flat=True))
        pending = list(
            RunDraft.objects.filter(
                run_job=run_job, draft_type=RunDraft.TYPE_INSIGHT, status=RunProposal.STATUS_PENDING,
            ).prefetch_related("news")
        )
        for draft in pending:
            if str(draft.pk) not in accepted_ids:
                draft.status = RunProposal.STATUS_REJECTED
                draft.save(update_fields=["status"])
                continue

            grade = request.POST.get(f"grade_{draft.pk}", "")
            if not grade:
                # grade_choices에는 "미지정"이 없지만(템플릿 계약), item.grade가 애초에
                # 비어 있던 초안은 select 맨 앞에 고를 수 없는 안내 option이 붙는다(템플릿
                # 상단 계약). 그 상태로 확정하면 여기로 빈 문자열이 온다 — 태그 교정
                # 대상을 못 찾았을 때와 같은 처리(messages.warning, 확정 전체는 막지 않음).
                grade = Insight.GRADE_UNSPECIFIED
                messages.warning(
                    request, f"'{draft.title}' 이슈에 등급을 고르지 않아 미지정으로 저장했어요.",
                )

            with transaction.atomic():
                insight = Insight.objects.create(
                    title=draft.title, content=draft.content, implication=draft.implication,
                    grade=grade,
                )
                insight.news.set(draft.news.all())
                draft.created_insight = insight
                draft.status = RunProposal.STATUS_ACCEPTED
                draft.save(update_fields=["created_insight", "status"])
            assigned_ids.update(n.pk for n in draft.news.all())

    dismissed_ids = candidate_ids - assigned_ids
    if dismissed_ids:
        News.objects.filter(
            pk__in=dismissed_ids, insights__isnull=True, insight_dismissed_at__isnull=True,
        ).update(insight_dismissed_at=timezone.now())


def _confirm_relation_drafts(request, run_jobs) -> None:
    """SET-010 3단계(주요 이슈) 확정 — 관계 초안(RunDraft.TYPE_RELATION) 갈래.
    채택된 초안마다 OrgRelation을 만들어 근거 News를 M2M으로 옮긴다(docs/planning.md
    "지식그래프 관계 라벨링을 3단계의 두 번째 LLM 호출로 옮긴다" 3-3·7번 —
    content→description, news M2M→relation.news, created_relation 채우기. 변환 없이
    이름이 같은 칸끼리 옮긴다).

    🔴 확정 POST가 받는 체크박스 이름은 "relation_ids"다("insight_ids"·"draft_ids"와
    다르다 — 같은 이유로 27차가 그 둘을 갈랐다, 같은 RunDraft 테이블을 가리키지만
    섞이면 확정 뷰가 이슈로 만들 것과 관계로 만들 것을 구분 못 한다). 🔴 PD 인계가
    아직 없어 이 이름은 이 함수가 정했다 — 인계가 오면 그 이름으로 맞춘다.

    🔴 `relation.news.set(...)`이 여기서는 안전하다 — 이 경로가 만드는 OrgRelation은
    항상 새로 만든 것뿐이다. 이미 OrgRelation이 있는 쌍은 제안 생성 시점에 걸러
    애초에 이 초안이 만들어지지 않는 것이 정책(같은 문서 6번) — 생성 쪽
    (services/runner.py)은 이번 라운드 범위 밖이라 아직 그 방어가 배선돼 있지
    않지만, 이 확정 경로 자체는 "생성"만 하지 기존 OrgRelation.news를 덮어쓰지
    않는다. ⚠️ PE가 놀랄 자리(같은 문서 말미) — "relation.news.set()은 추가가
    아니라 통째 교체"라는 함정은 GRAPH-001 편집 경로(graph_edge_label_save)의
    얘기이고, 그 함정은 "기존 관계를 편집"할 때만 닿는다. 여기는 매번 새 객체를
    만든 직후에 부르므로 지울 기존 근거 자체가 없다.

    🔴 unique_together(org_a, org_b) 충돌은 방어한다 — 제안 생성과 확정 사이에
    사람이 GRAPH-001에서 같은 쌍에 먼저 라벨을 붙였을 수 있는 레이스다. 그 경우
    사람이 이미 쓴 description을 덮어쓰지 않고 그 초안 하나만 건너뛴다
    (_confirm_report_drafts의 같은 방어와 형태를 맞췄다 — Report의
    unique_together(period_type, date_from) 레이스와 같은 성질)."""
    accepted_ids = set(request.POST.getlist("relation_ids"))
    pending = list(
        RunDraft.objects.filter(
            run_job__in=run_jobs, draft_type=RunDraft.TYPE_RELATION, status=RunProposal.STATUS_PENDING,
        ).select_related("relation_org_a", "relation_org_b").prefetch_related("news")
    )

    created_count = 0
    for draft in pending:
        if str(draft.pk) not in accepted_ids:
            draft.status = RunProposal.STATUS_REJECTED
            draft.save(update_fields=["status"])
            continue

        if not draft.relation_org_a_id or not draft.relation_org_b_id:
            # 실제로 날 수 있는 경우다 — 생성 쪽(services/runner.py)이 이번
            # 라운드에서 아직 배선되지 않아, 지금은 shell 등으로 직접 만든 행만
            # 있을 수 있고 그때 기업 쌍이 비면 OrgRelation을 만들 수 없다.
            logger.warning("RunDraft %s(관계) 확정 중 기업 쌍이 비어 있어 건너뛰었어요.", draft.pk)
            messages.warning(request, f"'{draft.title}' 관계는 기업 쌍이 없어 만들지 못했어요.")
            continue

        try:
            with transaction.atomic():
                relation = OrgRelation.objects.create(
                    org_a=draft.relation_org_a, org_b=draft.relation_org_b,
                    label=draft.relation_label, description=draft.content,
                )
                relation.news.set(draft.news.all())
                draft.created_relation = relation
                draft.status = RunProposal.STATUS_ACCEPTED
                draft.save(update_fields=["created_relation", "status"])
        except IntegrityError:
            logger.warning(
                "RunDraft %s(관계) 확정 중 같은 기업 쌍에 이미 OrgRelation이 있어 건너뛰었어요.",
                draft.pk,
            )
            messages.warning(
                request,
                f"'{draft.title}' 관계는 이미 다른 관계가 있어서 만들지 못했어요. "
                "지식그래프 화면에서 확인해 주세요.",
            )
            continue
        else:
            created_count += 1

    if created_count:
        messages.success(request, "관계를 만들었어요. 지식그래프에서 확인해 주세요.")


def _confirm_report_drafts(request, run_jobs, job_key) -> None:
    """SET-010 4, 5단계(주간·월간 보고서) 확정. 채택된 RunDraft마다 Report를 만들어
    근거 News를 M2M으로 옮긴다(설계 6번 표). 거절된 초안은 지우지 않고 상태만 남긴다
    — _confirm_insight_drafts()와 같은 원칙이다.

    🔴 확정 POST가 받는 체크박스 이름은 "draft_ids"다. "insight_ids"와 다르다
    (run_review.html 상단 계약 "확정 POST가 받는 값") — 같은 RunDraft 테이블을
    가리키지만 섞이면 확정 뷰가 이슈로 만들 것과 보고서로 만들 것을 구분하지 못한다.

    🔴 확정으로 만들어지는 Report는 status="generating"이다 — "아직 사람이 손봐야
    한다"는 뜻이고, done으로 바꾸는 주체는 RA이며 그 동작은 화면 밖(ORM)에서
    일어난다(설계 4번).

    🔴 Report.unique_together(period_type, date_from) 충돌은 사람이 읽을 수 있는
    메시지로 바꾼다(설계 2-1-(c) "확정 뷰에서 한 번 더 막는다") — 그대로 터지면
    500이다. 한 실행에 초안이 두 편 쌓인 날(재실행 등)에 실제로 걸릴 수 있다."""
    accepted_ids = set(request.POST.getlist("draft_ids"))
    pending = list(
        RunDraft.objects.filter(
            run_job__in=run_jobs, draft_type__in=(RunDraft.TYPE_WEEKLY, RunDraft.TYPE_MONTHLY),
            status=RunProposal.STATUS_PENDING,
        ).prefetch_related("news")
    )
    period_type = "weekly" if job_key == "weekly" else "monthly"

    created_count = 0
    for draft in pending:
        if str(draft.pk) not in accepted_ids:
            draft.status = RunProposal.STATUS_REJECTED
            draft.save(update_fields=["status"])
            continue

        try:
            with transaction.atomic():
                report = Report.objects.create(
                    period_type=period_type, date_from=draft.date_from, date_to=draft.date_to,
                    title=draft.title, overview=draft.overview, content=draft.content,
                    status="generating",
                )
                report.news.set(draft.news.all())
                draft.created_report = report
                draft.status = RunProposal.STATUS_ACCEPTED
                draft.save(update_fields=["created_report", "status"])
        except IntegrityError:
            logger.warning(
                "RunDraft %s(%s) 확정 중 같은 기간 보고서가 이미 있어 건너뛰었어요.",
                draft.pk, job_key,
            )
            messages.warning(
                request,
                "같은 기간 보고서가 이미 있어서 만들지 못했어요. "
                "실행 화면에서 검토 대기 목록을 확인해 주세요.",
            )
            continue
        else:
            created_count += 1

    if created_count:
        messages.success(request, "보고서를 만들었어요. 다듬고 나서 완료로 바꿔 주세요.")


@require_POST
def setting_run_review_confirm(request, job):
    """검토 화면의 확정 버튼. 체크된 제안은 채택해 실제로 반영하고, 대기 중이던 나머지
    제안은 거절로 남긴다 — 그 거절 분포가 프롬프트 정확도를 잴 유일한 정답지다
    (docs/planning.md 4-(b), run_review.html 상단 계약).

    처리 순서가 중요하다 — 삭제(①) → 중복 보도(②) → 태그 교정(③) → 태그 후보(④).
    같은 기사에 삭제 제안과 태그 제안이 함께 있고 삭제가 채택되면, News 자체가
    사라져 태그 교정의 대상이 없어진다(run_review.html 상단 계약 "삭제가 채택되면
    그 기사의 태그 교정은 저절로 대상이 사라진다") — 그 경우 거절이 아니라 취소로
    남긴다. 전제가 사라진 것이지 사람이 틀렸다고 판단한 게 아니라서, 거절 분포
    (프롬프트 정확도 지표)를 오염시키면 안 되기 때문이다. 🔴 중복 보도(②)를 삭제
    바로 뒤, 태그 교정보다 앞에 두는 이유도 같다 — deleted_news_ids가 ①에서 채워진
    뒤라야 ②가 같은 방어를 쓸 수 있다.

    🔴 개별 삭제(delete_news_with_record), 태그 교정(correct_news_tag)은 각자 내부에서
    이미 트랜잭션으로 묶여 있다 — 이 뷰를 통째로 하나의 트랜잭션으로 다시 감싸지
    않는다. 감싸면 한 건이 실패했을 때 그 실패를 잡아도 같은 트랜잭션 안의 나머지
    쓰기까지 함께 위험해진다(Django가 트랜잭션을 "깨짐"으로 표시). 건별로 이미 원자적인
    헬퍼를 그대로 믿고, 건별 실패는 개별 try/except로만 잡아 건수를 센다.

    🔴 중복 보도(②)는 삭제가 아니라 News.duplicate_of를 채우는 단순 필드 갱신이라
    실패할 일이 사실상 없다(대상을 찾지 못하는 경우 하나만 방어한다, 아래 hide_ids
    분기) — 그래서 delete_news_with_record()와 달리 try/except로 감싸지 않았다.
    이는 위 ①의 TYPE_KEEP 분기(단순 필드 갱신이라 그대로 저장)와 같은 판단이다."""
    if job not in RUN_JOB_KEYS:
        raise Http404

    # 🔴 2026-09-16 "SET-010 검토 단위" 절 확정 — 「가장 최근 RunJob 하나」가
    # 아니라 확정 대기 제안(또는 초안)이 있는 배치 전부를 확정한다. 확정하면
    # 관련 배치 전부가 확정됨이 된다 — 「확정됨」의 뜻은 "이 배치가 남긴 제안 중
    # 대기로 남은 것이 하나도 없다"이므로 여러 배치를 한 번에 확정해도 흐려지지
    # 않는다. 🔴 부분 확정은 없다 — run_jobs가 비어 있으면(볼 것이 없으면) 아무
    # 것도 하지 않고 조용히 돌려보낸다. B(미판정)가 남아 있는 채로 일부만
    # 확정하는 경로는 어디에도 없다(cleanup은 review 화면 자체가 B=0일 때만
    # 열린다 — 위 _job_run_state()).
    run_jobs = _pending_review_run_jobs(job)
    if not run_jobs:
        response = HttpResponse()
        response["HX-Redirect"] = reverse("setting_run")
        return response

    confirmed_at = timezone.now()

    if job == "insight":
        # 🔴 3단계(주요 이슈)는 산출물의 모양이 달라(설계 3번) RunProposal이 아니라
        # RunDraft를 다룬다 — 아래 삭제/태그 교정 경로와 완전히 갈라진 별도 확정 경로다.
        # 🔴 2026-09-17 — 같은 job_key 안에서 draft_type이 갈리는 두 번째 갈래(관계)를
        # 이어 부른다. 순서는 무관하다 — 둘은 서로 다른 draft_type으로 완전히 분리된
        # RunDraft 집합을 다루므로 겹치지 않는다.
        _confirm_insight_drafts(request, run_jobs)
        _confirm_relation_drafts(request, run_jobs)
        RunJob.objects.filter(pk__in=[rj.pk for rj in run_jobs]).update(
            status=RunJob.STATUS_CONFIRMED, confirmed_at=confirmed_at,
        )
        response = HttpResponse()
        response["HX-Redirect"] = reverse("setting_run")
        return response

    if job in ("weekly", "monthly"):
        # 🔴 4, 5단계(주간·월간 보고서)도 insight와 같은 이유로 RunDraft를 다루는
        # 별도 확정 경로다.
        _confirm_report_drafts(request, run_jobs, job)
        RunJob.objects.filter(pk__in=[rj.pk for rj in run_jobs]).update(
            status=RunJob.STATUS_CONFIRMED, confirmed_at=confirmed_at,
        )
        response = HttpResponse()
        response["HX-Redirect"] = reverse("setting_run")
        return response

    accepted_delete_ids = set(request.POST.getlist("delete_ids"))
    accepted_retag_ids = set(request.POST.getlist("retag_ids"))
    # 🔴 2026-09-17 28차 정정 신설(docs/design.md "SET-010 · 실행" 28차 정정 ⑤번) —
    # 중복 보도 카드의 체크박스 이름. delete_ids와 다른 이름이다 — 같은 이름으로
    # 오면 확정 뷰가 "지울 것"과 "감출 것"을 구분할 수단이 없어진다(모델 필드
    # docstring, 같은 이유로 27차가 insight_ids/draft_ids를 갈랐다).
    accepted_hide_ids = set(request.POST.getlist("hide_ids"))

    pending = list(
        RunProposal.objects.filter(run_job__in=run_jobs, status=RunProposal.STATUS_PENDING)
        .select_related("news")
    )
    relevance_proposals = [p for p in pending if p.proposal_type in (RunProposal.TYPE_DELETE, RunProposal.TYPE_KEEP)]
    tag_proposals = [p for p in pending if p.proposal_type in (RunProposal.TYPE_TAG_ADD, RunProposal.TYPE_TAG_REMOVE)]
    candidate_proposals = [p for p in pending if p.proposal_type == RunProposal.TYPE_TAG_CANDIDATE]
    dup_proposals = [p for p in pending if p.proposal_type == RunProposal.TYPE_DUPLICATE]

    delete_failed = 0
    tag_not_found = 0  # 대상 이름을 이름/별칭 어느 쪽으로도 찾지 못한 경우
    tag_error = 0       # 대상은 찾았지만 correct_news_tag() 실행 자체가 실패한 경우
    deleted_news_ids = set()
    newly_verified_news = []  # 이번 확정으로 검증됨으로 넘어간 News — 아래 회귀 검사용

    # ① 삭제/유지 — 태그 교정보다 먼저 처리한다(위 docstring 근거).
    for p in relevance_proposals:
        if p.proposal_type == RunProposal.TYPE_KEEP:
            # 유지는 체크박스가 없다 — 대기로 남아 있었다는 것 자체가 채택이다.
            p.news.status = News.STATUS_VERIFIED
            p.news.verified_at = timezone.now()
            p.news.save(update_fields=["status", "verified_at"])
            p.status = RunProposal.STATUS_ACCEPTED
            p.save(update_fields=["status"])
            newly_verified_news.append(p.news)
            continue

        if str(p.pk) not in accepted_delete_ids:
            # 🔴 2026-09-17 신설(docs/planning.md "검토 결과를 고도화 재료로 쓴다" 2·3·9번,
            # run_review.html 상단 계약 "확정 POST가 받는 값") — 거절 사유 수신자.
            # 삭제 제안(TYPE_DELETE)이 거절되는 자리는 이 분기뿐이다(TYPE_KEEP은
            # 항상 채택). required가 아니므로 안 왔거나 빈 문자열이면 "미기입"으로
            # 저장하고 확정을 그대로 진행한다 — 막으면 사람이 거절을 피해 정답지가
            # 줄어든다(같은 문서 "필수로 만들지 않는다"). "기타"일 때만 서술을 받는다
            # — 그 외 값에 서술이 실려 와도 버린다(값이 오적용/기준재검토인데 서술만
            # 채워지는 것은 어휘가 요구하지 않는 조합이다).
            reject_code = request.POST.get(f"reject_code_{p.pk}", "").strip()
            reject_code = reject_code or RunProposal.REJECT_CODE_UNSPECIFIED
            reject_note = (
                request.POST.get(f"reject_note_{p.pk}", "").strip()
                if reject_code == RunProposal.REJECT_CODE_OTHER else ""
            )
            p.status = RunProposal.STATUS_REJECTED
            p.reject_code = reject_code
            p.reject_note = reject_note
            p.save(update_fields=["status", "reject_code", "reject_note"])
            continue

        try:
            delete_news_with_record(
                p.news,
                criterion_code=p.criterion_code,
                reason=p.reason,
                # 🔴 2026-09-16 — 이 제안이 코드 사전 차단 규칙(RunProposal.judged_by,
                # services/cleanup_prefilter.py)이 낸 것이면 그 주체 값을 그대로
                # 넘긴다. 빈 값(LLM 판정)은 종전대로 JUDGED_BY_AUTO다 — 규칙 정확도와
                # LLM 정확도가 한 통계에 섞이지 않게 하려는 목적이다.
                judged_by=p.judged_by or DeletedNewsRecord.JUDGED_BY_AUTO,
            )
        except Exception:
            logger.exception("RunProposal %s(삭제) 확정 중 실패했어요.", p.pk)
            delete_failed += 1
            continue
        else:
            deleted_news_ids.add(p.news_id)
            # 🔴 p.save()가 아니라 pk로 좁힌 단건 update()를 쓴다. delete_news_with_record()가
            # 이 자리에서 News 인스턴스(p.news, 위에서 그대로 넘긴 그 객체)를 지우면서
            # Django가 그 인스턴스의 pk를 None으로 바꾸는데, p는 그 News를 캐시된 FK로 여전히
            # 물고 있어 p.save()를 부르면 "저장 안 된 관련 객체" 방어 검증에 걸려 죽는다
            # (ValueError: save() prohibited to prevent data loss due to unsaved related object
            # 'news'). update_fields=["status"]로 news 컬럼을 건드리지 않아도 이 검증은 인스턴스
            # 전체의 관계 캐시를 보고 판단해 막는다. filter(pk=...).update()는 이 인스턴스
            # 객체 그래프를 보지 않고 status 컬럼만 SQL로 직접 바꾸므로 걸리지 않는다 — 여러
            # 행을 건드리는 일괄 update가 아니라 이 한 행만 pk로 특정한 단건 갱신이다.
            RunProposal.objects.filter(pk=p.pk).update(status=RunProposal.STATUS_ACCEPTED)

    # 🔴 2026-09-16 회귀 검사(docs/planning.md "2단계 비용 절감 정책" 절, docs/design.md
    # "SET-010 · 실행" 21차 개정 ⑧번) — 실행 비용 0(LLM을 안 부른다). 방금 검증됨으로
    # 넘어간 News에 같은 사전 차단 규칙을 다시 돌려, "이 규칙이 지금 살아 있었다면
    # 걸렸을" 기사가 있는지 본다. 새 AI 관련 용어가 나왔는데 낱말 목록이 못 따라가면
    # 조용히 놓치기 시작하므로, 여기가 그걸 잡는 유일한 자리다. job == "cleanup"일
    # 때만 의미가 있다 — 다른 job은 relevance_proposals가 비어 있어
    # newly_verified_news도 항상 비어 있다.
    #
    # 🔴 알리는 자리가 둘이다(PD 21차 ⑧번) — ① 여기(messages.warning)는 확정 직후
    # 한 번 뜨고 사라진다. ② regression_flag_count는 RunJob에 남겨 "다음에 검토
    # 화면을 열 때"(_run_review_context()의 step.notice)도 보이게 한다 — 낱말 목록을
    # 넓히는 일은 코드를 고쳐야 해서 사용자가 그 자리에서 처리할 수 없기 때문이다.
    regression_flagged_count = 0
    if newly_verified_news:
        regression_flagged = [
            news for news in newly_verified_news
            if should_prefilter_delete(news.title, news.body)
        ]
        regression_flagged_count = len(regression_flagged)
        if regression_flagged:
            flagged_pks = ", ".join(str(news.pk) for news in regression_flagged)
            logger.warning(
                "2단계 회귀 검사: 검증됨으로 넘어간 %d건 중 %d건에 AI 낱말이 0회예요 "
                "(News pk: %s).",
                len(newly_verified_news), regression_flagged_count, flagged_pks,
            )
            # 🔴 문구는 PD가 정본이다(design.md 21차 ⑧번 권장 문안 ①).
            messages.warning(
                request,
                f"방금 통과한 기사 {regression_flagged_count}건은 규칙으로 걸러질 뻔했어요. "
                f"AI 관련 낱말을 넓혀야 해요.",
            )

    # ② 중복 보도 — 2026-09-17 28차 정정(docs/design.md "SET-010 · 실행" 28차 정정)
    # 신설. 채택하면 삭제하지 않고 News.duplicate_of에 그 묶음의 대표 pk를 넣어
    # 감춘다(NewsQuerySet.verified()가 duplicate_of__isnull=True로 걸러낸다).
    # RunProposal.duplicate_representative가 대표 News를 이미 들고 있으므로(모델
    # docstring) 화면이 대표 pk를 폼으로 보낼 필요가 없다.
    #
    # 🔴 삭제(①)보다 뒤, 태그 교정(③)보다 앞에 둔다 — deleted_news_ids가 위 ①에서
    # 이미 채워져 있어야 "이 기사가 이번에 삭제됐으면 감출 것도 없다"를 판단할 수
    # 있고(같은 기사에 삭제 제안과 중복 제안이 함께 걸리는 일은 구조상 없지만 방어는
    # 태그 교정과 같은 논리로 넣는다), 이 블록의 결과(hide_rep_missing 등)는 태그
    # 교정의 판단에 영향을 주지 않는다.
    hide_rep_missing = 0
    for p in dup_proposals:
        if p.news_id in deleted_news_ids:
            # 삭제 제안과 동시에 걸릴 구조가 아니지만(서로 다른 proposal_type이라
            # LLM이 같은 기사에 둘 다 내는 경우가 없다), 태그 교정과 같은 방어를
            # 넣어 둔다 — 감출 기사 자체가 사라지면 감출 것이 없다.
            p.status = RunProposal.STATUS_CANCELED
            p.save(update_fields=["status"])
            continue

        if str(p.pk) not in accepted_hide_ids:
            # 🔴 체크를 푸는 것이 「거절」인 자리라 삭제 제안과 같은 거절 사유
            # 칸을 그대로 쓴다(design.md 28차 정정 ⑤번 "중복 카드의 감출 행에도
            # 그대로 붙는다"). required가 아니므로 안 왔거나 빈 문자열이면
            # "미기입"으로 저장하고 확정을 그대로 진행한다.
            reject_code = request.POST.get(f"reject_code_{p.pk}", "").strip()
            reject_code = reject_code or RunProposal.REJECT_CODE_UNSPECIFIED
            reject_note = (
                request.POST.get(f"reject_note_{p.pk}", "").strip()
                if reject_code == RunProposal.REJECT_CODE_OTHER else ""
            )
            p.status = RunProposal.STATUS_REJECTED
            p.reject_code = reject_code
            p.reject_note = reject_note
            p.save(update_fields=["status", "reject_code", "reject_note"])
            continue

        if p.duplicate_representative_id is None:
            # 대표 News가 그사이 사라졌다(on_delete=SET_NULL) — 감출 곳이 없다.
            # 사람의 거절 판단이 아니므로 취소로 남긴다(아래 태그 교정의 "대상을
            # 못 찾음" 처리와 같은 논리 — 전제가 사라진 것이지 사람이 틀렸다고
            # 판단한 게 아니다).
            logger.warning(
                "RunProposal %s(중복 보도) 확정을 건너뛰었어요 — 대표 News가 사라졌어요.",
                p.pk,
            )
            hide_rep_missing += 1
            p.status = RunProposal.STATUS_CANCELED
            p.save(update_fields=["status"])
            continue

        # 🔴 삭제하지 않는다. News.duplicate_of만 채운다(설계 정본 "「삭제」가
        # 아니라 「감추기」입니다"). p.save()가 아니라 pk로 좁힌 update()를 쓴다 —
        # 대상 News가 이 요청 안에서 이미 불러온 인스턴스가 아니라 저장된 관계
        # 캐시에 얽매일 이유가 없는 단순 필드 갱신이다.
        News.objects.filter(pk=p.news_id).update(duplicate_of_id=p.duplicate_representative_id)
        RunProposal.objects.filter(pk=p.pk).update(status=RunProposal.STATUS_ACCEPTED)

    if hide_rep_missing:
        messages.warning(
            request, f"대표 기사가 사라져서 {hide_rep_missing}건은 감추지 못했어요.",
        )

    # ③ 태그 교정. 대상 조회는 collector의 별칭 매칭과 이름/별칭 비교 규칙을 그대로
    # 공유한다(services/collector.resolve_entity_by_name) — 수집 쪽 태깅은 이미 별칭을
    # 보는데 이 확정 경로만 name만 보고 있어서 같은 판정 규칙이 두 곳에서 갈리는 게
    # 근본 원인이었다(2026-09-15 실측: "KB금융" 등 3건이 별칭 미조회로 조용히 실패).
    from services.collector import resolve_entity_by_name
    all_orgs = list(Organization.objects.all())
    all_topics = list(TechTopic.objects.all())

    for p in tag_proposals:
        if p.news_id in deleted_news_ids:
            p.status = RunProposal.STATUS_CANCELED
            p.save(update_fields=["status"])
            continue

        if str(p.pk) not in accepted_retag_ids:
            p.status = RunProposal.STATUS_REJECTED
            p.save(update_fields=["status"])
            continue

        axis_label = dict(TagCorrectionRecord.AXIS_CHOICES).get(p.axis, p.axis)
        action_label = "추가" if p.proposal_type == RunProposal.TYPE_TAG_ADD else "제거"
        entities = all_orgs if p.axis == TagCorrectionRecord.AXIS_ORGANIZATION else all_topics
        target = resolve_entity_by_name(p.target_name, entities)

        if target is None:
            # 대상을 못 찾은 경우 — 사람이 이 제안을 틀렸다고 거절한 게 아니라 실행할
            # 대상 자체가 없는 것이라 거절(프롬프트 정확도 지표)이 아니라 취소로 남긴다.
            # 삭제된 기사의 태그 제안을 취소로 남기는 것과 같은 논리다.
            logger.warning(
                "RunProposal %s(태그 교정) 확정을 건너뛰었어요 — %s '%s'을(를) 찾지 못했어요.",
                p.pk, p.axis, p.target_name,
            )
            messages.warning(
                request,
                f"'{p.target_name}'이(가) {axis_label} 목록에 없어서 태그 {action_label}를 "
                f"건너뛰었어요. 필요하면 먼저 등록해 주세요.",
            )
            tag_not_found += 1
            p.status = RunProposal.STATUS_CANCELED
            p.save(update_fields=["status"])
            continue

        try:
            correct_news_tag(
                p.news, target,
                action=(
                    TagCorrectionRecord.ACTION_ADD if p.proposal_type == RunProposal.TYPE_TAG_ADD
                    else TagCorrectionRecord.ACTION_REMOVE
                ),
                reason=p.reason,
                judged_by=TagCorrectionRecord.JUDGED_BY_AUTO,
            )
        except Exception:
            # 대상은 찾았지만 실행 자체가 실패한 경우 — 이것도 사람의 거절 판단이
            # 아니므로 같은 이유로 취소로 남긴다. 원인이 다르므로(대상 없음 대 실행
            # 예외) 카운터는 tag_not_found와 tag_error로 나눠 센다.
            logger.exception("RunProposal %s(태그 교정) 확정 중 실패했어요.", p.pk)
            messages.warning(
                request,
                f"'{p.target_name}' 태그 {action_label} 처리 중 오류가 나서 건너뛰었어요.",
            )
            tag_error += 1
            p.status = RunProposal.STATUS_CANCELED
            p.save(update_fields=["status"])
            continue
        else:
            p.status = RunProposal.STATUS_ACCEPTED
            p.save(update_fields=["status"])

    # ④ 태그 후보(기업 또는 기술 주제) — 아무 것도 실행하지 않는다(Organization·
    # TechTopic을 만들지 않는다). 채택도 거절도 아니라서 취소로 남긴다(design.md 4차
    # 개정 ⑩번 "후보 종류는 아무 것도 하지 않는다", 2026-09-15 축 일반화 이후에도
    # 그대로 상속되는 성질 — docs/planning.md 4-(b) 개정).
    for p in candidate_proposals:
        p.status = RunProposal.STATUS_CANCELED
        p.save(update_fields=["status"])

    # 🔴 regression_flagged_count는 "cleanup" 확정에서만 뜻이 있다(위 규칙 회귀 검사
    # 블록 참고) — 다른 job은 newly_verified_news가 항상 비어 있어 0 그대로다. 이번
    # 확정에 묶인 배치 전부에 같은 값을 남긴다 — confirmed_at을 이미 똑같이 채우는
    # 것과 같은 방식이다.
    RunJob.objects.filter(pk__in=[rj.pk for rj in run_jobs]).update(
        status=RunJob.STATUS_CONFIRMED, confirmed_at=confirmed_at,
        regression_flag_count=regression_flagged_count,
    )

    if delete_failed or tag_not_found or tag_error or hide_rep_missing:
        logger.warning(
            "RunJob %s(%s) 확정 중 삭제 실패 %d건, 중복 보도 대표 없음 %d건, "
            "태그 교정 대상 못 찾음 %d건, 태그 교정 실행 실패 %d건이었어요.",
            [rj.pk for rj in run_jobs], job, delete_failed, hide_rep_missing,
            tag_not_found, tag_error,
        )

    response = HttpResponse()
    response["HX-Redirect"] = reverse("setting_run")
    return response


@require_POST
def setting_run_review_cancel(request, job):
    """검토 화면의 "모두 취소". 🔴 종전에는 아무 것도 하지 않는 스텁이었다 — 초안이나
    제안이 0건으로 끝난 배치(3단계는 "묶을 이슈가 없는 날" 등)가 확정 버튼도 잠긴 채
    검토 대기에 영영 남는 교착이 났다(run_review.html 상단 계약 "3단계에서 cancel_url을
    반드시 채운다").

    대기 중이던 RunProposal·RunDraft는 지우지 않고 취소로 남긴다(거절과 다른 값 —
    사람이 내용을 보고 거절한 게 아니라 통째로 버린 것이라 거절 분포를 오염시키지
    않는다, 확정 뷰의 같은 판단과 동일). 실제 데이터(News·Insight 등)는 아무것도
    건드리지 않는다.

    🔴 2026-09-16 "SET-010 검토 단위" 절 확정 — 범위가 「화면에 보이는 것 전부」다.
    배치를 골라 일부만 취소하지 않는다(_pending_review_run_jobs()가 검토 화면과
    똑같은 목록을 본다) — "pk107만 버리고 pk130은 남긴다"는 실행 사정을 사람이
    다시 떠안는 일이라, 이 설계가 없애려는 것과 같은 자리다."""
    if job not in RUN_JOB_KEYS:
        raise Http404

    run_jobs = _pending_review_run_jobs(job)
    if run_jobs:
        RunProposal.objects.filter(run_job__in=run_jobs, status=RunProposal.STATUS_PENDING).update(
            status=RunProposal.STATUS_CANCELED,
        )
        RunDraft.objects.filter(run_job__in=run_jobs, status=RunProposal.STATUS_PENDING).update(
            status=RunProposal.STATUS_CANCELED,
        )
        RunJob.objects.filter(pk__in=[rj.pk for rj in run_jobs]).update(
            status=RunJob.STATUS_CANCELED,
        )

    response = HttpResponse()
    response["HX-Redirect"] = reverse("setting_run")
    return response


def _render_tag_candidate_controls(proposal, message: str, retry: bool = False) -> str:
    """23차 개정(design.md 「SET-010 · 실행」 23차 ③) — 검토 화면의 미등록 태그
    등록 컨트롤 조각을 문자열로 만든다. 🔴 templates/ 아래 새 파일을 만들지 않는다
    — 이 라운드는 templates/와 docs/design.md를 PD 담당으로 남겨 둔다. 그 대신
    이 뷰가 컨트롤 묶음을 대신할 짧은 조각을 직접 만든다.

    retry=False면 그 자리를 짧은 상태 문장으로 갈아 끼운다("등록했어요" 등) —
    후보 행 자체(이름·이유·기사 정보)는 이 조각 밖에 있어 그대로 남는다.
    retry=True면 유형을 다시 고를 수 있게 입력을 되살린다(예: 유형을 안 골랐을
    때) — hx-post/hx-target/hx-include를 원본 마크업과 똑같이 다시 붙여야
    재시도가 된다.

    ⚠️ <i data-lucide>를 쓰지 않는다. swap 뒤에 createIcons()를 다시 돌리지
    않으면 빈 칸으로 남는다(run_review.html 상단 계약)."""
    from django.utils.html import format_html, format_html_join

    root_id = f"tagcand-{proposal.pk}"
    if not retry:
        return format_html(
            '<div id="{}" class="flex-shrink-0 text-xs text-gray-500">{}</div>', root_id, message,
        )

    register_url = reverse("setting_run_tag_candidate_register", args=[proposal.pk])
    select_html = ""
    if proposal.axis == TagCorrectionRecord.AXIS_ORGANIZATION:
        options = format_html_join(
            "", "<option value=\"{}\">{}</option>", Organization.ORG_TYPE_CHOICES,
        )
        select_html = format_html(
            '<select name="cand_org_type" class="w-28 text-xs border border-[#E5E5E5] '
            'rounded-[10px] px-2 py-1.5 focus:outline-none focus:border-primary">'
            '<option value="">유형 선택</option>{}</select>',
            options,
        )
    return format_html(
        '<div id="{root_id}" class="flex-shrink-0 flex flex-col items-end gap-1">'
        '<p class="text-[11px] text-orange-600">{message}</p>'
        '<div class="flex items-center gap-2">'
        "{select}"
        '<input type="text" name="cand_aliases" placeholder="별칭 (쉼표로 구분)" '
        'class="w-32 text-xs border border-[#E5E5E5] rounded-[10px] px-2 py-1.5 '
        'focus:outline-none focus:border-primary">'
        '<button type="button" hx-post="{register_url}" hx-target="#{root_id}" '
        'hx-swap="outerHTML" '
        'hx-include="#{root_id} select, #{root_id} input, [name=csrfmiddlewaretoken]" '
        'hx-disabled-elt="this" '
        'class="flex-shrink-0 px-3 py-1.5 text-xs font-medium text-white bg-primary '
        'rounded-[10px] hover:bg-primary-hover transition-colors">등록</button>'
        "</div></div>",
        root_id=root_id, message=message, select=select_html, register_url=register_url,
    )


@require_POST
def setting_run_tag_candidate_register(request, pk):
    """검토 화면에서 태그 후보를 그 줄에서 바로 등록한다(design.md 「SET-010 ·
    실행」 23차 ③, docs/planning.md 4-(b) 2026-09-15 개정 "기업 후보를 태그
    후보로 일반화").

    🔴 이름은 입력으로 받지 않는다 — RunProposal.target_name을 그대로 쓴다.
    고쳐 쓰게 두면 제안과 등록이 다른 이름이 되어 다음 실행에서 같은 후보가
    또 뜬다(이름을 바꿔야 하면 그건 SET-007·SET-008의 일이다).

    🔴 remap을 부르지 않는다 — 등록은 새 레코드를 만드는 것까지다.
    `remap_organizations()`는 사람이 손으로 고친 태그를 되돌리므로, 기업을 새로
    등록할 때 기본은 미실행이다(docs/planning.md 4-(b), CLAUDE.md 패턴 4와 같은
    자리 — "remap은 사람이 손으로 고친 태그를 원복한다").

    이름이 이미 등록돼 있으면(이름 또는 별칭) 새로 만들지 않고 "이미 등록돼
    있어요"로 답한다 — 중복 생성은 이 제안 종류의 목적과 반대다.

    🔴 2026-09-17 버그 수정 — "이미 등록돼 있음" 확인을 유형 검증보다 먼저
    한다. 같은 이름의 태그 후보가 기사마다 따로 제안돼 화면에 여러 줄로
    뜨는 것은 정상이다(서로 다른 RunProposal이라 proposal_id·id도 각자
    유일하다 — 확인함). 문제는 그중 한 줄로 이미 등록한 뒤 나머지 줄에서도
    등록을 누르면, 유형을 다시 고르지 않는 한(같은 이름을 또 등록할 이유가
    없다고 여기는 게 자연스럽다) 실제 원인("이미 등록됨")과 무관한 "유형을
    선택해 주세요"가 되풀이해서 떴다 — 순서를 바꾸면 유형을 안 골라도 바로
    맞는 이유가 뜬다."""
    proposal = get_object_or_404(RunProposal, pk=pk, proposal_type=RunProposal.TYPE_TAG_CANDIDATE)
    name = proposal.target_name.strip()

    from services.collector import resolve_entity_by_name

    if proposal.axis == TagCorrectionRecord.AXIS_ORGANIZATION:
        if resolve_entity_by_name(name, list(Organization.objects.all())):
            html = _render_tag_candidate_controls(proposal, "이미 등록돼 있어요")
            return HttpResponse(html)
        org_type = request.POST.get("cand_org_type", "").strip()
        if org_type not in dict(Organization.ORG_TYPE_CHOICES):
            html = _render_tag_candidate_controls(proposal, "유형을 선택해 주세요", retry=True)
            return HttpResponse(html)
        aliases = [a.strip() for a in request.POST.get("cand_aliases", "").split(",") if a.strip()]
        Organization.objects.create(name=name, org_type=org_type, aliases=aliases)
    elif proposal.axis == TagCorrectionRecord.AXIS_TECH_TOPIC:
        if resolve_entity_by_name(name, list(TechTopic.objects.all())):
            html = _render_tag_candidate_controls(proposal, "이미 등록돼 있어요")
            return HttpResponse(html)
        aliases = [a.strip() for a in request.POST.get("cand_aliases", "").split(",") if a.strip()]
        TechTopic.objects.create(name=name, aliases=aliases)
    else:
        # axis가 빈 문자열 등 알 수 없는 값 — 어느 표에 등록해야 할지 모르는 채로
        # 만들면 틀린 곳에 들어간다(run_review.html 상단 계약, 그룹 머리 링크를
        # 감추는 조건과 같은 판단).
        html = _render_tag_candidate_controls(proposal, "분류를 알 수 없어요")
        return HttpResponse(html)

    return HttpResponse(_render_tag_candidate_controls(proposal, "등록했어요"))


@require_POST
def source_toggle(request, pk):
    source = get_object_or_404(DataSource, pk=pk)
    source.is_active = not source.is_active
    source.save()
    return render(request, "setting/_sources.html", _source_context())


def _keyword_context():
    return {
        "collect_keywords": Keyword.objects.filter(keyword_type=Keyword.TYPE_COLLECT, is_active=True),
        "exclude_keywords": Keyword.objects.filter(keyword_type=Keyword.TYPE_EXCLUDE, is_active=True),
        "TYPE_COLLECT": Keyword.TYPE_COLLECT,
        "TYPE_EXCLUDE": Keyword.TYPE_EXCLUDE,
        "SORT_CHOICES": Keyword.SORT_CHOICES,
    }


def keywords(request):
    return render(request, "setting/keywords.html", {
        "setting_menu": _setting_menu("keywords"),
        **_keyword_context(),
    })


@require_POST
def keyword_update(request, pk):
    kw = get_object_or_404(Keyword, pk=pk)
    keyword = request.POST.get("keyword", "").strip()
    sort    = request.POST.get("sort", kw.sort)
    if keyword:
        kw.keyword = keyword
        kw.sort    = sort
        kw.save()
    return render(request, "setting/_keywords.html", _keyword_context())


@require_POST
def keyword_add(request):
    keyword      = request.POST.get("keyword", "").strip()
    keyword_type = request.POST.get("keyword_type", Keyword.TYPE_COLLECT)
    sort         = request.POST.get("sort", Keyword.SORT_DATE)
    if keyword:
        Keyword.objects.get_or_create(
            keyword=keyword,
            keyword_type=keyword_type,
            sort=sort,
        )
    return render(request, "setting/_keywords.html", _keyword_context())


@require_POST
def keyword_delete(request, pk):
    Keyword.objects.filter(pk=pk).delete()
    return render(request, "setting/_keywords.html", _keyword_context())


def slack(request):
    from apps.reports.models import Report
    if request.method == "POST":
        config = SlackConfig.objects.first() or SlackConfig()
        config.channel_name = request.POST.get("channel_name", "")
        # SET-009와 같은 계약으로 미리 맞춰 둔다(마스킹 인풋으로 PD가 템플릿을
        # 바꿀 예정 — 그 전까지는 템플릿이 value를 채워 보내므로 ③으로 떨어져
        # 지금과 동일하게 그대로 저장된다). 순서가 뜻을 가진다:
        # ① clear=="1" → 빈 문자열로 저장(최우선)
        # ② 키가 없거나("disabled" 인풋) 빈 값 → 아무것도 하지 않는다(기존 값 유지)
        # ③ 값이 있으면 strip 후 저장
        if request.POST.get("webhook_url_clear") == "1":
            config.webhook_url = ""
        elif request.POST.get("webhook_url"):
            config.webhook_url = request.POST.get("webhook_url").strip()
        config.is_active = "is_active" in request.POST
        config.save()
        return redirect("setting_slack")
    config = SlackConfig.objects.first()
    sent_reports = Report.objects.exclude(slack_sent_at=None).order_by("-slack_sent_at")[:10]
    return render(request, "setting/slack.html", {
        "setting_menu": _setting_menu("slack"),
        "config": config,
        "sent_reports": sent_reports,
    })


def _verification_pipeline_context():
    """SET-006 "검증 파이프라인 현황" 카드용 운영 관측 값 3종
    (docs/planning.md "검증 게이트" 5번, docs/design.md SET-006 절 PE 컨텍스트 변수 계약).
    unverified_tier의 임계값 판단은 여기(뷰)에 두고 템플릿에는 문자열만 내려준다 —
    나중에 임계값을 조정할 때 템플릿을 건드리지 않기 위해서(PD 설계 의도)."""
    unverified_qs = News.objects.filter(status=News.STATUS_UNVERIFIED)
    unverified_count = unverified_qs.count()

    oldest_collected_at = unverified_qs.aggregate(Min("collected_at"))["collected_at__min"]
    oldest_unverified_at = (
        timezone.localtime(oldest_collected_at).date() if oldest_collected_at else None
    )
    today = timezone.localtime(timezone.now()).date()
    unverified_days = (today - oldest_unverified_at).days if oldest_unverified_at else None

    if unverified_count == 0:
        unverified_tier = "clear"
    elif unverified_days is not None and unverified_days >= UNVERIFIED_STALE_DAYS:
        unverified_tier = "stale"
    else:
        unverified_tier = "pending"

    last_verified_at = News.objects.filter(
        status=News.STATUS_VERIFIED
    ).aggregate(Max("verified_at"))["verified_at__max"]

    return {
        "unverified_count": unverified_count,
        "oldest_unverified_at": oldest_unverified_at,
        "unverified_days": unverified_days,
        "unverified_tier": unverified_tier,
        "last_verified_at": last_verified_at,
        "orphan_relation_count": _orphan_relation_count(),
    }


def _orphan_relation_count() -> int:
    """SET-006 "고아 라벨 관계" 지표(docs/planning.md "지식그래프 엣지 노출 규칙 최종 확정:
    라벨 AND 기간" 4번, docs/design.md SET-006 절 orphan_relation_count 계약).

    정의: 전체 기간 기준으로도 두 기업이 함께 언급된 검증 뉴스가 0건인 OrgRelation(라벨 있는 관계)
    건수. GRAPH-001의 엣지 노출 게이트(라벨 있음 AND 선택 기간 내 검증 뉴스 공동언급 ≥ 1건)를
    "전체" 기간으로도 만족하지 못하는 관계라 — 어떤 기간을 선택해도 화면에 나타나지 않는다.

    상관 서브쿼리(Exists)로 count() 호출 1번에 끝낸다 — OrgRelation을 순회하며 매번 쿼리를 날리지
    않는다. 두 번 체이닝한 .filter()로 organizations 교집합(AND)을 구현하는 방식은
    apps/graph/views.py의 _edge_news_queryset과 동일 패턴이다(organizations__in=[a, b] 같은
    단일 필터는 합집합(OR)이 되어 오답을 낸다)."""
    common_news = (
        News.objects.verified()
        .filter(organizations=OuterRef("org_a"))
        .filter(organizations=OuterRef("org_b"))
    )
    return (
        OrgRelation.objects
        .annotate(has_common_news=Exists(common_news))
        .filter(has_common_news=False)
        .count()
    )


# SET-006 「실행 이력과 비용」(docs/design.md 1차 개정, 2026-09-16) 페이지 크기. 두 탭
# (수집 로그/실행 이력) 모두 20건/쪽이다(PD 확정, ⑦번 "무한 스크롤을 쓰지 않는다").
LOG_PAGE_SIZE = 20


def _paginate_log(queryset, request, param):
    """SET-006 두 탭(수집 로그 cpage / 실행 이력 rpage)이 공유하는 페이지네이션 헬퍼.
    templates/setting/_log_pagination.html이 받는 (page, page_range) 튜플을 만든다.
    page_range 항목은 정수이거나 Paginator.ELLIPSIS("…") 문자열인데, 템플릿의
    `{% if num == "…" %}` 비교가 항상 문자열과 맞도록 str()로 한 번 더 캐스팅해 넘긴다
    (docs/design.md PE 인계 계약 "문자열 '…'")."""
    paginator = Paginator(queryset, LOG_PAGE_SIZE)
    try:
        page = paginator.page(request.GET.get(param, 1))
    except PageNotAnInteger:
        page = paginator.page(1)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)
    page_range = [
        n if isinstance(n, int) else str(n)
        for n in paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)
    ]
    return page, page_range


def _run_cost_summary(queryset):
    """RunJob 쿼리셋 하나의 (비용 합계 원, 실행 건수) — SET-006 "쓴 비용" 카드의 오늘/이번
    달/전체 세 칸이 각각 이 함수를 한 번씩 부른다. 페이지가 아니라 기간 전체를 집계하므로
    페이지를 넘겨도 이 값은 바뀌지 않는다(PE 인계 계약 4번)."""
    agg = queryset.aggregate(
        input_sum=Sum("input_tokens"),
        output_sum=Sum("output_tokens"),
        cache_write_sum=Sum("cache_creation_input_tokens"),
        cache_read_sum=Sum("cache_read_input_tokens"),
        run_count=Count("pk"),
    )
    cost_krw = compute_cost_krw(
        agg["input_sum"] or 0, agg["output_sum"] or 0,
        agg["cache_write_sum"] or 0, agg["cache_read_sum"] or 0,
    )
    return cost_krw, agg["run_count"] or 0


def _run_row(run_job):
    """RunJob 한 건을 SET-006 실행 이력 표의 한 행(dict)으로 바꾼다(PE 인계 계약
    "run_rows 각 항목의 키"). axis는 job_key가 NEWSROOM_JOB_KEYS에 속하는지로 가른다 —
    RUN_JOB_LABELS의 "1단계 수집"이 리서치·소식 양쪽에 있어 배지 없이는 구분되지 않는다."""
    is_newsroom = run_job.job_key in NEWSROOM_JOB_KEYS
    return {
        "started_at": run_job.started_at,
        "axis": "newsroom" if is_newsroom else "research",
        "axis_label": "소식" if is_newsroom else "리서치",
        "step_label": RUN_JOB_LABELS.get(run_job.job_key, run_job.job_key),
        "status": run_job.status,
        "status_label": run_job.get_status_display(),
        "processed_count": run_job.processed_count,
        "failed_count": run_job.failed_count,
        "input_tokens": run_job.input_tokens,
        "output_tokens": run_job.output_tokens,
        "cache_write_tokens": run_job.cache_creation_input_tokens,
        "cache_read_tokens": run_job.cache_read_input_tokens,
        "cost_krw": compute_cost_krw(
            run_job.input_tokens, run_job.output_tokens,
            run_job.cache_creation_input_tokens, run_job.cache_read_input_tokens,
        ),
    }


def logs(request):
    # ?tab= 화이트리스트(docs/design.md PE 인계 계약) — 엉뚱한 값이 오면 기본값으로
    # 조용히 떨어진다(에러를 내지 않는다, 조회 전용 화면이라 사고 위험이 없다).
    active_tab = request.GET.get("tab")
    if active_tab not in ("collection", "runs"):
        active_tab = "collection"

    collection_page, collection_page_range = _paginate_log(
        CollectionLog.objects.select_related("source").order_by("-started_at"), request, "cpage",
    )
    run_page, run_page_range = _paginate_log(
        RunJob.objects.order_by("-started_at", "-pk"), request, "rpage",
    )
    run_rows = [_run_row(run_job) for run_job in run_page.object_list]

    today = _today_local()
    month_start = today.replace(day=1)
    cost_today_krw, runs_today_count = _run_cost_summary(RunJob.objects.filter(started_at__date=today))
    cost_month_krw, runs_month_count = _run_cost_summary(
        RunJob.objects.filter(started_at__date__gte=month_start, started_at__date__lte=today)
    )
    cost_total_krw, runs_total_count = _run_cost_summary(RunJob.objects.all())

    return render(request, "setting/logs.html", {
        "setting_menu": _setting_menu("logs"),
        "active_tab": active_tab,
        "collection_page": collection_page,
        "collection_page_range": collection_page_range,
        "run_page": run_page,
        "run_page_range": run_page_range,
        "run_rows": run_rows,
        "cost_today_krw": cost_today_krw,
        "cost_month_krw": cost_month_krw,
        "cost_total_krw": cost_total_krw,
        "runs_today_count": runs_today_count,
        "runs_month_count": runs_month_count,
        "runs_total_count": runs_total_count,
        "cost_rates": {
            "input": PRICE_PER_MILLION_TOKENS_USD["input"],
            "output": PRICE_PER_MILLION_TOKENS_USD["output"],
            "cache_write": PRICE_PER_MILLION_TOKENS_USD["cache_write"],
            "cache_read": PRICE_PER_MILLION_TOKENS_USD["cache_read"],
            "usd_krw": USD_KRW,
        },
        **_verification_pipeline_context(),
    })


def _org_context():
    orgs = list(Organization.objects.all())
    grouped = []
    for value, label in Organization.ORG_TYPE_CHOICES:
        group_orgs = [o for o in orgs if o.org_type == value]
        grouped.append({"type": value, "label": label, "orgs": group_orgs, "count": len(group_orgs)})
    return {
        "grouped": grouped,
        "org_types": Organization.ORG_TYPE_CHOICES,
        "total_count": len(orgs),
    }


def organizations(request):
    return render(request, "setting/organizations.html", {
        "setting_menu": _setting_menu("organizations"),
        **_org_context(),
    })


@require_POST
def organization_save(request):
    org_id = request.POST.get("org_id", "").strip()
    name = request.POST.get("name", "").strip()
    org_type = request.POST.get("org_type", "")
    aliases = [a.strip() for a in request.POST.get("aliases", "").split(",") if a.strip()]
    if org_id:
        org = get_object_or_404(Organization, pk=org_id)
        org.name = name
        org.org_type = org_type
        org.aliases = aliases
        org.save()
    elif name and org_type:
        Organization.objects.get_or_create(name=name, defaults={"org_type": org_type, "aliases": aliases})
    return render(request, "setting/_organizations.html", _org_context())


@require_POST
def organization_toggle(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    org.is_active = not org.is_active
    org.save()
    return render(request, "setting/_organizations.html", _org_context())


@require_POST
def organization_delete(request, pk):
    Organization.objects.filter(pk=pk).delete()
    return render(request, "setting/_organizations.html", _org_context())


def _tech_topic_context():
    topics = TechTopic.objects.annotate(news_count=Count("news", distinct=True)).all()
    return {
        "topics": topics,
        "total_count": topics.count(),
    }


def tech_topics(request):
    return render(request, "setting/tech_topics.html", {
        "setting_menu": _setting_menu("tech_topics"),
        **_tech_topic_context(),
    })


@require_POST
def tech_topic_save(request):
    topic_id = request.POST.get("topic_id", "").strip()
    name = request.POST.get("name", "").strip()
    aliases = [a.strip() for a in request.POST.get("aliases", "").split(",") if a.strip()]
    if topic_id:
        topic = get_object_or_404(TechTopic, pk=topic_id)
        topic.name = name
        topic.aliases = aliases
        topic.save()
    elif name:
        TechTopic.objects.get_or_create(name=name, defaults={"aliases": aliases})
    return render(request, "setting/_tech_topics.html", _tech_topic_context())


@require_POST
def tech_topic_toggle(request, pk):
    topic = get_object_or_404(TechTopic, pk=pk)
    topic.is_active = not topic.is_active
    topic.save()
    return render(request, "setting/_tech_topics.html", _tech_topic_context())


@require_POST
def tech_topic_delete(request, pk):
    TechTopic.objects.filter(pk=pk).delete()
    return render(request, "setting/_tech_topics.html", _tech_topic_context())


@require_POST
def remap_now(request):
    from services.collector import remap_organizations
    count = remap_organizations()
    return render(request, "setting/_remap_result.html", {"remap_count": count, "entity_label": "기업"})


@require_POST
def remap_tech_topics_now(request):
    from services.collector import remap_tech_topics
    count = remap_tech_topics()
    return render(request, "setting/_remap_result.html", {"remap_count": count, "entity_label": "기술 주제"})


# --- SET-009 뉴스룸 관리 ---
# docs/design.md SET-009 절 인계: "SET-009 뷰는 apps/setting/views.py에 두고 모델을 import
# 한다(_setting_menu()가 이 앱에 있고 이미 apps.news를 import하고 있어 일관된다)."


def setting_newsroom(request):
    from apps.newsroom.models import Newsroom, NewsroomKeyword
    rooms = list(Newsroom.objects.all())

    # 저장 후 선택 상태를 되살리는 값(?selected=<pk>) — 사용자 입력을 그대로 Alpine
    # x-data(JS 컨텍스트)에 꽂으면 안 되므로, 실제 rooms 중 하나의 pk와 일치할 때만
    # 받아들인다(그 외엔 첫 번째 뉴스룸으로 폴백). rooms.0.id처럼 템플릿에서 빈
    # 쿼리셋을 직접 인덱싱하면 VariableDoesNotExist가 필터 인자 자리에서 그대로
    # 튀어나와 500이 나므로(Django가 필터 인자 레벨에서는 이 예외를 삼키지 않는다),
    # "선택할 뉴스룸이 있는지·무엇인지"는 뷰에서 미리 정리해 내려준다.
    selected_param = request.GET.get("selected", "")
    room_ids = {room.pk for room in rooms}
    if selected_param.isdigit() and int(selected_param) in room_ids:
        initial_selected = int(selected_param)
    else:
        initial_selected = rooms[0].pk if rooms else None

    return render(request, "setting/newsroom.html", {
        "setting_menu": _setting_menu("newsroom"),
        "rooms": rooms,
        "initial_selected": initial_selected,
        "SORT_CHOICES": NewsroomKeyword.SORT_CHOICES,
        "hour_choices": [f"{h:02d}" for h in range(24)],
        "minute_choices": ["00", "10", "20", "30", "40", "50"],
        "freq_choices": Newsroom.FREQ_CHOICES,
    })


@require_POST
def setting_newsroom_save(request):
    from apps.newsroom.models import Newsroom

    room_id = request.POST.get("room_id", "").strip()
    name = request.POST.get("name", "").strip()

    if room_id:
        room = get_object_or_404(Newsroom, pk=room_id)
        # 편집 패널의 "기본" 섹션에만 활성 체크박스가 있다 — 기존 뉴스룸을 그 폼으로
        # 저장할 때만 POST 값으로 갱신한다.
        room.is_active = "is_active" in request.POST
    elif name:
        room = Newsroom()
        # "+ 새 뉴스룸" 모달에는 활성 체크박스가 없다. 여기서 위와 같이
        # `"is_active" in request.POST`를 그대로 쓰면 모달 POST에는 그 키가 없어
        # 항상 False가 되고, 모델 기본값(True)을 조용히 덮어쓴다 — 실제로 이 버그로
        # 새로 만든 뉴스룸이 전부 "멈춤"으로 보였다(2026-09-02 발견). 새 뉴스룸은
        # Newsroom.is_active의 모델 기본값(True)을 그대로 둔다.
    else:
        return redirect("setting_newsroom")

    room.name = name
    room.description = request.POST.get("description", "").strip()
    room.filter_prompt = request.POST.get("filter_prompt", "")
    room.compose_prompt = request.POST.get("compose_prompt", "")
    room.slack_channel_name = request.POST.get("slack_channel_name", "").strip()
    # Webhook 주소는 마스킹 인풋이라 평문 재노출을 하지 않는다(SET-009 설계).
    # value가 내려가지 않으므로 "빈 값 = 건드리지 않음"이 기본이고, 명시적으로
    # 지울 때만 slack_webhook_clear="1"을 함께 보낸다. 순서가 뜻을 가진다:
    # ① clear=="1" → 빈 문자열로 저장(최우선)
    # ② 키가 없거나("disabled" 인풋) 빈 값 → 아무것도 하지 않는다(기존 값 유지)
    # ③ 값이 있으면 strip 후 저장
    if request.POST.get("slack_webhook_clear") == "1":
        room.slack_webhook_url = ""
    elif request.POST.get("slack_webhook_url"):
        room.slack_webhook_url = request.POST.get("slack_webhook_url").strip()

    send_hour = request.POST.get("send_hour", "").strip()
    if send_hour.isdigit():
        room.send_hour = int(send_hour)
    send_minute = request.POST.get("send_minute", "").strip()
    if send_minute.isdigit():
        room.send_minute = int(send_minute)
    room.send_frequency = request.POST.get("send_frequency", Newsroom.FREQ_WEEKDAY)
    room.send_is_active = "send_is_active" in request.POST

    room.save()
    return redirect(f"{reverse('setting_newsroom')}?selected={room.pk}")


@require_POST
def setting_newsroom_delete(request, pk):
    from apps.newsroom.models import Newsroom
    from django.http import HttpResponse
    Newsroom.objects.filter(pk=pk).delete()
    response = HttpResponse()
    response["HX-Redirect"] = reverse("setting_newsroom")
    return response


def _newsroom_keyword_context(room):
    from apps.newsroom.models import NewsroomKeyword
    return {
        "room": room,
        "keywords": room.keywords.all(),
        "SORT_CHOICES": NewsroomKeyword.SORT_CHOICES,
    }


@require_POST
def setting_newsroom_keyword_add(request, room_pk):
    from apps.newsroom.models import Newsroom, NewsroomKeyword
    room = get_object_or_404(Newsroom, pk=room_pk)
    keyword = request.POST.get("keyword", "").strip()
    sort = request.POST.get("sort", NewsroomKeyword.SORT_DATE)
    display = request.POST.get("display", "").strip()
    if keyword:
        NewsroomKeyword.objects.get_or_create(
            newsroom=room,
            keyword=keyword,
            defaults={
                "sort": sort,
                "display": int(display) if display.isdigit() else 20,
            },
        )
    return render(request, "setting/_newsroom_keywords.html", _newsroom_keyword_context(room))


@require_POST
def setting_newsroom_keyword_update(request, room_pk, pk):
    from apps.newsroom.models import Newsroom, NewsroomKeyword
    room = get_object_or_404(Newsroom, pk=room_pk)
    kw = get_object_or_404(NewsroomKeyword, pk=pk, newsroom=room)
    keyword = request.POST.get("keyword", "").strip()
    if keyword:
        kw.keyword = keyword
        kw.sort = request.POST.get("sort", kw.sort)
        display = request.POST.get("display", "").strip()
        if display.isdigit():
            kw.display = int(display)
        kw.save()
    return render(request, "setting/_newsroom_keywords.html", _newsroom_keyword_context(room))


@require_POST
def setting_newsroom_keyword_delete(request, room_pk, pk):
    from apps.newsroom.models import Newsroom, NewsroomKeyword
    room = get_object_or_404(Newsroom, pk=room_pk)
    NewsroomKeyword.objects.filter(pk=pk, newsroom=room).delete()
    return render(request, "setting/_newsroom_keywords.html", _newsroom_keyword_context(room))


@require_POST
def setting_newsroom_message_mark_sent(request, pk):
    """SET-009 발송 섹션(setting/_newsroom_message.html)의 「보냈다고 표시하기」
    (docs/planning.md 뉴스룸 정책 12-3 (d)).

    🔴 sent_at이 이미 있으면 덮어쓰지 않는다 — 두 사람이 거의 동시에 눌러도 먼저
    찍힌 시각이 보존된다. 나중 요청이 덮으면 "언제 나갔나"가 틀어진다.
    🔴 「표시 되돌리기」는 만들지 않는다(비대칭이 의도, 12-3 (d)) — 잘못 표시해도
    복사 버튼이 그대로 살아 있어 그냥 다시 보내면 되고, 되돌릴 수 있으면 두 번째
    사람이 또 붙여 넣는다. 그래서 이 뷰에는 취소·되돌리기 분기 자체가 없다.

    HTMX가 이 조각(_newsroom_message.html)만 갈아 끼운다(hx-target + hx-swap
    innerHTML) — 페이지 전체를 다시 그리면 열어 둔 채널 선택(Alpine)과 자동 높이
    조절된 프롬프트 textarea가 초기화된다."""
    from apps.newsroom.models import NewsroomMessage
    message = get_object_or_404(NewsroomMessage, pk=pk)
    if not message.sent_at:
        message.sent_at = timezone.now()
        message.status = NewsroomMessage.STATUS_SENT_MANUAL
        message.save(update_fields=["sent_at", "status"])
    return render(request, "setting/_newsroom_message.html", {"room": message.newsroom})
