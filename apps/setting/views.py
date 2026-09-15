import logging

from django.conf import settings
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Count, Min, Max, Exists, OuterRef
from django.http import Http404, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.news.models import DeletedNewsRecord, Insight, News, TagCorrectionRecord
from apps.news.services import correct_news_tag, delete_news_with_record
from apps.reports.models import Report
from .models import (
    DataSource, Keyword, CollectionLog, LLMLog, SlackConfig,
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


def _source_context():
    return {"sources": DataSource.objects.all()}


def sources(request):
    return render(request, "setting/sources.html", {
        "setting_menu": _setting_menu("sources"),
        **_source_context(),
    })


# --- SET-010 실행 (수동 LLM 실행 + 승인 게이트) ---
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
    "cleanup": "2단계 뉴스 정리",
    "insight": "3단계 주요 이슈",
    "weekly": "4단계 주간 보고서",
    "monthly": "5단계 월간 보고서",
    "newsroom_collect": "1단계 수집",
    "newsroom_filter": "2단계 필터",
    "newsroom_compose": "3단계 발송문",
    "newsroom_send": "4단계 발송",
}

# 완료(STATUS_DONE)여도 승인 게이트가 있는 job은 사람이 확정을 누르기 전까지 "검토
# 대기"로 보여야 한다(apps/setting/models.py RunJob docstring "완료와 확정됨을 반드시
# 구분한다" 원칙). 승인 게이트가 없는 collect/newsroom_collect는 이 목록에 넣지 않는다
# — 그 둘은 STATUS_DONE이 곧 "더 할 일 없음"이다.
# 🔴 2026-09-15 PE 개정 — "insight"를 추가했다. _run_review_context()가 _job_run_state()를
# 그대로 불러 검토 화면 머리글 상태를 만들므로, 여기 없으면 초안이 쌓인 배치도 review
# 화면에서 "완료"로 잘못 찍힌다.
# 🔴 2026-09-15 2라운드 — 메인 그래프(_research_jobs_context)도 이번에 insight 버튼을
# 열었다(선행 잠금 _insight_block_reason()과 함께). 위 문단이 말하는 "검토 대기" 전환은
# 그 버튼이 열렸든 닫혔든 GATED_JOB_KEYS만 보고 동작하므로 이 상수 자체는 그대로다.
#
# 🔴 같은 날 뒤이은 라운드 — "weekly"·"monthly"를 더한다(4, 5단계). 둘 다 확정하면
# Report가 실제로 생기는 승인 게이트가 있으므로 완료 즉시가 아니라 검토 대기를 거친다.
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
# _run_node.html에서 정한다. 여기 없는 job_key(아직 미구현)는 빈 문자열로 떨어진다.
PROGRESS_UNIT_BY_JOB = {
    "collect": "키워드",
    "cleanup": "기사",
    "newsroom_collect": "키워드",
    "newsroom_filter": "기사",
}

# 중단 요약(state=='stopped')의 세 갈래(PD 확정, 2026-09-15) — "다시 누르면 어디서부터인가"가
# 단계마다 다르다. collect/newsroom_collect는 collector 중복 체크가 이미 받은 기사를
# 걸러 이어받고, cleanup/newsroom_filter는 제안이 이미 있는 기사가 다음 대상에서 빠져
# 남은 건부터 잇지만, insight/weekly/monthly(1호출 단계)는 중간이 없어 처음부터 다시
# 돈다 — 그 갈래엔 건수를 찍지 않는다("29건까지 했다"가 "29건은 남아 있겠지"로 오독된다).
RESUME_FROM_SCRATCH_JOB_KEYS = ("insight", "weekly", "monthly")

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
    "cleanup": "기사마다 관련성을 판정했어요", "insight": "같은 사건을 이슈로 묶었어요",
    "weekly": "이슈를 모아 주간 보고서를 썼어요", "monthly": "이슈를 모아 월간 결산을 썼어요",
}

# 🔴 2026-09-15 2라운드 PE 신설 — _run_job_display()의 "대상 0건" 교착 방지 분기(아래)가
# 쓰는 job_key별 요약 문구. GATED_JOB_KEYS 두 job의 "대상"이 서로 다른 말이라(cleanup은
# 미검증 뉴스, insight는 이슈로 묶을 뉴스) 문구도 갈라야 한다 — 하나로 고정해 두면
# insight가 대상 0건으로 끝났을 때 "정리할 미검증 뉴스가 없었어요"라는, insight와
# 무관한(cleanup 전용) 문장이 그대로 찍힌다. 실제로 인위 RunJob(job_key="insight",
# target_count=0)으로 재현해 확인한 문제다(트랜잭션 롤백 검증, 커밋하지 않음).
ZERO_TARGET_SUMMARY_BY_JOB = {
    "cleanup": "정리할 미검증 뉴스가 없었어요",
    "insight": "이슈로 묶을 뉴스가 없었어요",
    # 🔴 같은 날 뒤이은 라운드 — 없으면 cleanup 전용 문구("정리할 미검증 뉴스가
    # 없었어요")가 그대로 찍혀 4, 5단계와 무관한 문장이 뜬다.
    "weekly": "이번 주에 만들어진 이슈가 없었어요",
    "monthly": "지난달에 만들어진 이슈가 없었어요",
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


def _job_run_state(run_job, job_key):
    """RunJob.status를 화면 어휘(idle/running/review/done/failed/stopped)로 바꾼다.
    _run_job_display()(노드 그래프)와 검토 화면 머리글이 이 함수를 함께 써서, 같은
    상태를 두 화면이 다른 말로 부르는 것을 막는다(_run_node.html "상태 배지" 주석의
    원칙 — "한국어 텍스트가 정본이고 테두리 색은 훑기용 보조")."""
    if run_job.status == RunJob.STATUS_RUNNING:
        return "running", "실행 중"
    if run_job.status == RunJob.STATUS_STOPPED:
        return "stopped", "중단됨"
    if run_job.status == RunJob.STATUS_FAILED:
        return "failed", "실패"
    if run_job.status == RunJob.STATUS_DONE:
        # 🔴 대상 0건이면 검토할 제안 자체가 없다(RunProposal이 하나도 없다). 그런데도
        # review로 보내면 노드는 "결과 검토하기"만 내주고 검토 화면은 확정 버튼이 잠겨
        # 있어(isDisabled(), 커버리지 0) 빠져나갈 길이 없는 교착에 빠진다 — 2026-09-15에
        # 실제로 사용자가 이 상태에 갇혀 RunJob을 손으로 취소됨으로 바꿔야 했다.
        # 대상이 없으면 애초에 검토할 것도 없으므로 done으로 내려 실행 버튼을 그대로
        # 돌려준다.
        if job_key in GATED_JOB_KEYS and run_job.target_count > 0:
            return "review", "검토 대기"
        return "done", "완료"
    if run_job.status == RunJob.STATUS_CONFIRMED:
        return "done", "확정됨"
    if run_job.status == RunJob.STATUS_CANCELED:
        return "done", "취소됨"
    return "idle", "대기"


def _run_job_display(job_key):
    """job_key의 최신 RunJob으로 노드 표시값(state/state_label/summary/elapsed)을
    만든다. 그 job_key로 RunJob이 한 번도 없었으면 None을 반환한다 — 호출부가 기존
    방식(CollectionLog, NewsroomArticle.collected_at)으로 idle/done을 채운다.

    상태 어휘는 _job_run_state()가 정한다 — templates/setting/_run_node.html이 아는
    값(idle/running/review/done/failed/stopped)만 나온다. STATUS_STOPPED(중단됨)는
    2026-09-14에 전용 주황 배지가 생겨(_run_node.html) 이제 'stopped'를 그대로
    내린다 — 종전에는 전용 색이 없어 'failed'로 눌러 담았었다."""
    run_job = RunJob.objects.filter(job_key=job_key).order_by("-started_at", "-pk").first()
    if not run_job:
        return None
    state, state_label = _job_run_state(run_job, job_key)
    if state == "running":
        seconds = int((timezone.now() - run_job.started_at).total_seconds())
        elapsed = f"{seconds // 60}분 {seconds % 60}초째" if seconds >= 60 else f"{seconds}초째"
        display = {
            "state": state, "state_label": state_label, "summary": "", "elapsed": elapsed,
            # 🔴 분자는 처리를 마친 수(성공+실패)다(docs/planning.md "SET-010 진행 표시"
            # 5-(a)) — processed_count만 쓰면 실패가 섞인 배치가 목표 건수(target_count)에
            # 끝내 못 닿은 채 완료돼, "71건 중 68건"에서 멈춘 것처럼 보인다. DB 필드
            # (processed_count)의 뜻 자체는 바꾸지 않는다 — 검토 화면과 로그가 그 뜻으로
            # 읽는다. 여기서 합치는 건 화면에 내리는 값뿐이다.
            "progress_current": run_job.processed_count + run_job.failed_count,
            "progress_total": run_job.target_count,
            "progress_unit": PROGRESS_UNIT_BY_JOB.get(job_key, ""),
        }
        if run_job.failed_count:
            display["progress_failed"] = run_job.failed_count
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
        else:  # cleanup, newsroom_filter
            summary = (
                f"{PROGRESS_UNIT_BY_JOB.get(job_key, '')} {run_job.target_count}건 중 {current}건까지 "
                "판정하고 멈췄어요. 남은 기사부터 이어해요"
            )
        return {"state": state, "state_label": state_label, "summary": summary}
    if state == "failed":
        return {"state": state, "state_label": state_label, "summary": "실행이 실패했어요"}
    if state == "review":
        return {
            "state": state, "state_label": state_label,
            "summary": f"{run_job.processed_count}건 판정을 마쳤어요, 검토를 기다리고 있어요",
        }
    if run_job.status == RunJob.STATUS_DONE:
        if job_key in GATED_JOB_KEYS and run_job.target_count == 0:
            # 대상 0건 교착 방지(위 _job_run_state 주석과 같은 사고) — state는 이미
            # "done"으로 내려오므로(review로 가지 않는다) 요약 문구만 그 사정에 맞게
            # 따로 말해 준다. job_key마다 "대상"이 다른 말이라 ZERO_TARGET_SUMMARY_BY_JOB로
            # 갈라 쓴다(위 정의 주석 참고).
            summary = ZERO_TARGET_SUMMARY_BY_JOB.get(job_key, "처리할 대상이 없었어요")
            return {"state": state, "state_label": state_label, "summary": summary}
        return {
            "state": state, "state_label": state_label,
            "summary": f"마지막 실행 {timezone.localtime(run_job.finished_at):%m/%d %H:%M}, {run_job.processed_count}건",
        }
    if run_job.status == RunJob.STATUS_CONFIRMED:
        return {
            "state": state, "state_label": state_label,
            "summary": f"마지막 확정 {timezone.localtime(run_job.finished_at):%m/%d %H:%M}, {run_job.processed_count}건",
        }
    # 대기/취소됨 — 이번 라운드는 여기 닿지 않는다(collect/newsroom_collect는 확정·취소
    # 상태로 가는 경로가 없고, cleanup도 확정 전까지는 대기를 거치지 않는다).
    return None


def _current_running_job():
    """지금 시스템 전체에서 진행중인 RunJob(있으면 그 인스턴스, 없으면 None).
    run.html/_run_graph.html의 running_job 컨텍스트 키 그대로다 — 두 템플릿 모두
    이 값을 진위값으로만 쓴다(속성 접근 없음). 읽기 전에 하트비트가 끊긴 진행중
    RunJob을 먼저 중단됨으로 정리한다(감시 프로세스 없이 읽는 쪽이 판정, 문서
    3-(e))."""
    from services.runner import mark_stale_running_as_stopped
    mark_stale_running_as_stopped()
    return RunJob.objects.filter(status=RunJob.STATUS_RUNNING).order_by("-started_at").first()


def _insight_block_reason() -> str:
    """3단계(주요 이슈) 선행 잠금 사유. 빈 문자열이면 잠기지 않는다(docs/planning.md
    "3~5단계를 LLM으로 옮기는 설계" 2번 표, PM 설계 "선행 미완은 경고가 아니라 버튼
    잠금이다"). 순서가 뜻을 가진다 — 먼저 걸리는 조건의 문구가 화면에 뜬다.

    🔴 두 번째 조건(확정되지 않은 cleanup 배치)은 위 표에 없는 방어 조건이다. 보통은
    첫 조건(미검증 News 존재)이 먼저 걸린다 — cleanup 배치가 확정 전이면 그 배치가
    다뤘던 News는 여전히 미검증 상태로 남기 때문이다(확정 뷰에서만 상태가 바뀐다).
    다만 그 배치의 대상 News가 NEWS-002에서 개별로 먼저 삭제되면(ExcludedURL 경로)
    미검증 건수가 0으로 떨어지면서도 그 배치 자체는 여전히 확정 전이라, 첫 조건만으로는
    못 잡는 틈이 생긴다. RunJob 상태를 직접 봐서 그 틈을 막는다."""
    unverified_count = News.objects.filter(status=News.STATUS_UNVERIFIED).count()
    if unverified_count:
        return f"아직 정리되지 않은 뉴스가 {unverified_count}건 있어요"

    pending_cleanup = RunJob.objects.filter(job_key="cleanup", status=RunJob.STATUS_DONE).exists()
    if pending_cleanup:
        return "2단계 정리 결과를 아직 확정하지 않았어요"

    unassigned_count = News.objects.verified().filter(insights__isnull=True).count()
    if unassigned_count == 0:
        return "이슈로 묶을 뉴스가 없어요"

    return ""


def _weekly_job_context():
    """run.html/_run_graph.html의 research_jobs["weekly"](4단계 주간 보고서).

    🔴 대상 주는 services/report_periods.target_week() 단 하나로 계산한다 — 확정
    시점의 Report.date_from/date_to 저장도 services/runner.py가 같은 함수를 쓴다
    (docs/planning.md "3~5단계를 LLM으로 옮기는 설계" 2-1-(d) "뷰가 날짜를 따로
    계산하지 않는다"). "대상 기간에 Insight가 0건이다" 판정도 같은 문서의
    insights_in_period()를 그대로 쓴다.

    🔴 잠금 사유가 둘로 갈린다(설계 2-1) — 같은 조건("대상 주 Report가 이미 있다")이
    "아직 만들 때가 아니다"(오늘이 그 주 밖)와 "이미 만들었다"(오늘이 그 주 안)를
    함께 가리킬 수 있어서다. 순서는 0건 판정이 먼저다(설계 2번 표 "이슈 0건이면 두
    경우 모두 이번 주에 만들어진 이슈가 없어요가 앞선다").

    🔴 summary도 함께 바꾼다(templates/setting/run.html 상단 계약 "summary와
    block_reason을 짝으로 쓰는 단계들") — block_reason은 마우스를 올려야 보이고
    항상 보이는 줄은 summary 하나다. 이미 쓴 보고서가 있어 잠긴 경우, summary가
    "9월 2주차를 9/12에 썼어요"처럼 주차 표기를 남겨야 block_reason의 "금요일부터"가
    어느 주를 가리키는지 사람이 알 수 있다."""
    from services.report_periods import insights_in_period, target_week

    today = timezone.localtime(timezone.now()).date()
    date_from, date_to = target_week(today)

    display = _run_job_display("weekly")
    job = display or {"state": "idle", "state_label": "대기", "summary": ""}

    can_run, block_reason = True, ""
    if not insights_in_period(date_from, date_to).exists():
        can_run, block_reason = False, "이번 주에 만들어진 이슈가 없어요"
    else:
        existing = Report.objects.filter(period_type="weekly", date_from=date_from).first()
        if existing:
            can_run = False
            block_reason = (
                "이번 주 보고서가 이미 있어요" if date_from <= today <= date_to
                else "주간 보고서는 금요일부터 만들 수 있어요"
            )
            week_no = (existing.date_to.day - 1) // 7 + 1
            written = timezone.localtime(existing.created_at)
            job["summary"] = (
                f"{existing.date_to.month}월 {week_no}주차를 {written.month}/{written.day}에 썼어요"
            )

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
    해당하는 조건이 없다(설계 2-1-(b) 2번)."""
    from services.report_periods import insights_in_period, target_month

    today = timezone.localtime(timezone.now()).date()
    date_from, date_to = target_month(today)

    display = _run_job_display("monthly")
    job = display or {"state": "idle", "state_label": "대기", "summary": ""}

    can_run, block_reason = True, ""
    if not insights_in_period(date_from, date_to).exists():
        can_run, block_reason = False, "지난달에 만들어진 이슈가 없어요"
    else:
        existing = Report.objects.filter(period_type="monthly", date_from=date_from).first()
        if existing:
            can_run, block_reason = False, "지난달 결산이 이미 있어요"
            written = timezone.localtime(existing.created_at)
            job["summary"] = (
                f"{existing.date_from.month}월분을 {written.month}/{written.day}에 썼어요"
            )

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
    run_display = _run_job_display("collect")
    if run_display:
        collect_job = run_display
    else:
        latest = CollectionLog.objects.order_by("-started_at").first()
        if latest:
            failed = latest.status == "fail"
            collect_job = {
                "state": "failed" if failed else "done",
                "state_label": "실패" if failed else "완료",
                "summary": f"마지막 수집 {timezone.localtime(latest.started_at):%m/%d %H:%M}",
            }
        else:
            collect_job = {"state": "idle", "state_label": "대기", "summary": ""}

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
    cleanup_display = _run_job_display("cleanup")
    cleanup_job = cleanup_display or {"state": "idle", "state_label": "대기", "summary": ""}
    cleanup_job.update({
        "can_run": True,
        "block_reason": "",
        "warning": "",
        "confirm_text": "",
        "run_url": reverse("setting_run_start", args=["cleanup"]),
        "review_url": reverse("setting_run_review", args=["cleanup"]),
    })
    jobs["cleanup"] = cleanup_job

    # 3단계 주요 이슈 — 이번 라운드에서 실행 버튼을 연다(services/runner.py
    # IMPLEMENTED_JOB_KEYS에 "insight" 추가와 짝을 이룬다). GATED_JOB_KEYS에 "insight"가
    # 이미 있어(이전 라운드) 완료(STATUS_DONE)면 _run_job_display()가 그대로
    # state="review"를 내려 cleanup과 똑같이 "결과 검토하기" 버튼으로 바뀐다 — 여기서
    # 따로 분기하지 않는다. can_run/block_reason만 _insight_block_reason()이 결정한다
    # (PM 설계 "선행 미완은 경고가 아니라 버튼 잠금이다").
    insight_display = _run_job_display("insight")
    insight_job = insight_display or {"state": "idle", "state_label": "대기", "summary": ""}
    insight_block_reason = _insight_block_reason()
    insight_job.update({
        "can_run": not insight_block_reason,
        "block_reason": insight_block_reason,
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
    return jobs


def _target_newsroom():
    """SET-010 교보 소식 1단계 수집의 대상 채널을 고른다. _setting_menu()/newsroom_nav가
    쓰는 "활성 채널이 1개면 그것" 규칙과 같은 방식이다(코디네이터 지시) — 채널이
    여러 개로 늘면 그때 다시 판단한다. 활성이 0개거나 2개 이상이면 어느 채널을 돌릴지
    정할 수 없으므로 None을 반환하고, 호출부가 그 이유를 block_reason으로 내려준다."""
    from apps.newsroom.models import Newsroom
    active_rooms = list(Newsroom.objects.filter(is_active=True))
    return active_rooms[0] if len(active_rooms) == 1 else None


def _newsroom_jobs_context():
    """run.html/_run_graph.html의 newsroom_jobs(교보 소식 축, 4개 키 고정).
    1단계 수집만 apps/newsroom/services.py의 collect_newsroom()을 실제로 부른다.
    🔴 2026-09-14 — SET-009 "지금 수집" 버튼이 같은 함수를 요청 스레드에서 직접
    불러 RunJob 전역 잠금을 거치지 않는 두 번째 진입점이었다(SET-001의 collect_now와
    같은 유형의 버그). 그 버튼을 철거해 지금은 이 축의 유일한 호출부다.
    2~4단계는 미구현이라 NOT_IMPLEMENTED_REASON으로 비활성이다."""
    from apps.newsroom.models import Newsroom, NewsroomArticle

    room = _target_newsroom()
    if room:
        run_display = _run_job_display("newsroom_collect")
        if run_display:
            collect_job = run_display
        else:
            latest_article = NewsroomArticle.objects.filter(newsroom=room).order_by("-collected_at").first()
            if latest_article:
                collect_job = {
                    "state": "done",
                    "state_label": "완료",
                    # CollectionLog는 본 파이프라인 전용이라 여기 쓰지 않는다(코디네이터 지시) —
                    # 마지막 실행 요약은 NewsroomArticle.collected_at으로 만든다.
                    "summary": f"마지막 수집 {timezone.localtime(latest_article.collected_at):%m/%d %H:%M}",
                }
            else:
                collect_job = {"state": "idle", "state_label": "대기", "summary": ""}
        collect_job.update({
            "can_run": True,
            "block_reason": "",
            "warning": "",
            "confirm_text": "",
            "run_url": reverse("setting_run_start", args=["newsroom_collect"]),
            "review_url": "",
        })
    else:
        no_room_reason = (
            "수집할 채널이 없어요" if not Newsroom.objects.filter(is_active=True).exists()
            else "활성 채널이 여러 개라 어느 채널인지 정할 수 없어요"
        )
        collect_job = {
            "state": "idle", "state_label": "대기", "summary": no_room_reason,
            "can_run": False, "block_reason": no_room_reason,
            "warning": "", "confirm_text": "", "run_url": "", "review_url": "",
        }

    jobs = {"newsroom_collect": collect_job}
    for key in NEWSROOM_JOB_KEYS[1:]:
        jobs[key] = {
            "state": "idle",
            "state_label": "대기",
            "summary": NOT_IMPLEMENTED_REASON,
            "can_run": False,
            "block_reason": NOT_IMPLEMENTED_REASON,
            "warning": "",
            "confirm_text": "",
            "run_url": "",
            "review_url": reverse("setting_run_review", args=[key]),
        }
    return jobs


def setting_run(request):
    return render(request, "setting/run.html", {
        "setting_menu": _setting_menu("run"),
        "graph_url": reverse("setting_run_graph"),
        "running_job": _current_running_job(),
        "research_jobs": _research_jobs_context(),
        "newsroom_jobs": _newsroom_jobs_context(),
    })


def setting_run_graph(request):
    """폴링 대상 조각(3초). running_job이 있어야 _run_graph.html이 폴링 트리거를
    단다 — _current_running_job()이 RunJob을 실제로 읽으므로, 이제 이 뷰는 실행
    중일 때 3초마다 반복 호출된다."""
    return render(request, "setting/_run_graph.html", {
        "graph_url": reverse("setting_run_graph"),
        "running_job": _current_running_job(),
        "research_jobs": _research_jobs_context(),
        "newsroom_jobs": _newsroom_jobs_context(),
    })


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
    # 나머지 세 단계(뉴스룸 2~4단계) — services/llm.py의 판정 로직이 아직 없다.
    # 노드 자체가 run_url 없이 비활성이라 UI에서는 여기로 POST가 오지 않지만,
    # 직접 호출되더라도 그래프를 안전하게 다시 그려 준다.
    #
    # start_run()은 RunJob을 만들고 워커 스레드를 띄운 뒤 즉시 반환한다 — 여기서
    # 수집이 끝나기를 기다리지 않는다(gunicorn 요청 타임아웃에 걸리지 않는 이유,
    # docs/planning.md "실행 모델" 3-(d)). 이미 다른 작업이 진행중이면 start_run()이
    # None을 반환하고 아무것도 새로 만들지 않는다 — 아래 그래프 재렌더는 그 현재
    # 상태(진행중인 다른 작업)를 그대로 보여준다.
    return render(request, "setting/_run_graph.html", {
        "graph_url": reverse("setting_run_graph"),
        "running_job": _current_running_job(),
        "research_jobs": _research_jobs_context(),
        "newsroom_jobs": _newsroom_jobs_context(),
    })


BODY_PREVIEW_CHARS = 300


def _body_preview(body: str) -> str:
    """삭제 제안 행의 본문 미리보기. 전체 본문을 그대로 내려보내지 않는다 —
    run_review.html의 x-show 펼침 칸 하나에 쓰일 짧은 분량이면 충분하다."""
    if len(body) <= BODY_PREVIEW_CHARS:
        return body
    return body[:BODY_PREVIEW_CHARS] + "..."


def _format_duration(seconds: int) -> str:
    """review.step.duration 등에 쓰는 소요 시간 문자열. _run_job_display()의 elapsed
    포맷("1분 12초째")과 같은 자리수 규칙을 쓰되 접미사 "째"는 붙이지 않는다 — elapsed는
    "지금 몇 초째"(진행 중, 계속 갱신)를 말하고 이건 "다 걸린 시간"(완료, 고정값)을
    말해 뜻이 다르다."""
    return f"{seconds // 60}분 {seconds % 60}초" if seconds >= 60 else f"{seconds}초"


def _collected_period(proposals) -> str:
    """review.input.period — 이 배치가 다룬 뉴스의 수집일 범위(예: "09.02 ~ 09.03").
    RunJob은 대상 News 목록 자체를 따로 저장하지 않으므로, 이 배치가 남긴
    RunProposal이 참조하는 News.collected_at으로 근사한다 — 판정 도중 실패해 제안이
    생기지 않은 대상은 이 범위에서 빠지지만(연속 3회 실패면 배치 자체가 끊기므로
    실패 건수는 대개 0이거나 소수다), 범위가 하루 이틀 단위로 넓어 그 편차가 눈에 띄는
    차이를 만들지 않는다."""
    dates = sorted({timezone.localtime(p.news.collected_at).date() for p in proposals if p.news_id})
    if not dates:
        return ""
    if dates[0] == dates[-1]:
        return f"{dates[0]:%m.%d}"
    return f"{dates[0]:%m.%d} ~ {dates[-1]:%m.%d}"


def _insight_items_context(run_job):
    """SET-010 3단계(주요 이슈) 검토 화면의 insight_items 목록. 계약은
    templates/setting/run_review.html 상단 주석 "insight_items" 절이 정본이다.

    🔴 id는 RunDraft.pk다(News.pk가 아니다) — 확정 POST의 grade_<id>·insight_ids가
    이 값을 그대로 되돌려 보낸다.

    🔴 news_items의 url은 News.uid로 만든다(pk가 아니다) — NEWS-002의 URL 패턴이
    <shortuuid:uid>다(apps/news/urls.py). 3단계 입력은 이미 검증된 News라 실제로
    열린다(2단계 삭제 목록과 달리 404가 아니다, 템플릿 상단 계약 "근거 기사를 새 탭으로
    여는 이유")."""
    drafts = list(
        RunDraft.objects.filter(
            run_job=run_job, draft_type=RunDraft.TYPE_INSIGHT, status=RunProposal.STATUS_PENDING,
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


def _report_items_context(run_job):
    """SET-010 4, 5단계(주간·월간 보고서) 검토 화면의 report_items 목록. 계약은
    templates/setting/run_review.html 상단 주석 "report_items" 절이 정본이다.

    🔴 주간과 월간이 이 한 함수를 같이 쓴다 — 갈리는 것은 draft_type 필터뿐이고
    그 값은 services/runner.py._run_report()가 이미 job_key별로 다르게 저장해
    뒀다. body_label만 job_key로 갈라 내린다(월간은 "주요 이슈 요약", REPORT-002가
    그렇게 부른다).

    🔴 id는 RunDraft.pk다 — 확정 POST의 draft_ids가 이 값을 그대로 되돌려 보낸다.
    🔴 grade/implication은 내리지 않는다 — 보고서 초안에는 그 두 칸이 없다(RunDraft
    docstring, "이슈 전용" 필드)."""
    drafts = list(
        RunDraft.objects.filter(
            run_job=run_job, draft_type__in=(RunDraft.TYPE_WEEKLY, RunDraft.TYPE_MONTHLY),
            status=RunProposal.STATUS_PENDING,
        ).prefetch_related("news").order_by("pk")
    )
    body_label = "주요 이슈 요약" if run_job.job_key == "monthly" else "주요 이슈"
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
    }

    run_job = RunJob.objects.filter(job_key=job_key).order_by("-started_at", "-pk").first()
    if run_job is None:
        return review

    state, state_label = _job_run_state(run_job, job_key)
    review["run"] = {
        "label": f"{timezone.localtime(run_job.started_at):%m/%d %H:%M} 실행" if run_job.started_at else "",
        "state": state,
        "state_label": state_label,
        "progress": (
            # 🔴 분자는 처리를 마친 수(성공+실패)다 — _run_job_display()의 같은 자리와
            # 같은 이유(docs/planning.md "SET-010 진행 표시" 5-(a)). processed_count만
            # 쓰면 실패가 섞인 배치가 "116건 중 113건"처럼 목표 건수에 못 닿은 채로
            # 보인다.
            f"{run_job.target_count}건 중 {run_job.processed_count + run_job.failed_count}건 처리"
            if run_job.target_count else ""
        ),
        "failed_str": f"실패 {run_job.failed_count}건" if run_job.failed_count else "",
        "resumable": state == "stopped",
    }

    proposals = list(
        RunProposal.objects.filter(run_job=run_job, status=RunProposal.STATUS_PENDING)
        .select_related("news")
        .order_by("-news__published_at", "news_id", "pk")
    )

    # docs/design.md 5차 개정 ⑦ PE 인계 — review.input/review.step을 채운다. cleanup만
    # 실제 LLM 판정 배치가 있어(REVIEW_*_BY_JOB) 지금은 그 job_key만 채워진다.
    review["input"] = {}
    if job_key in REVIEW_INPUT_LABEL_BY_JOB:
        # 🔴 target_count는 run_job이 존재하는 한 항상 "알려진 값"이다(0도 "정말 0건"이지
        # "아직 못 받았다"가 아니다) — run_job이 없는 경우는 위에서 이미 조기 반환했다.
        review["input"] = {
            "count": run_job.target_count,
            "label": REVIEW_INPUT_LABEL_BY_JOB[job_key],
            "period": _collected_period(proposals),
        }

    step = {"prompt_version": run_job.prompt_version}
    if job_key in REVIEW_STEP_SUMMARY_BY_JOB:
        step["summary"] = REVIEW_STEP_SUMMARY_BY_JOB[job_key]
        model_setting_key = REVIEW_MODEL_KEY_BY_JOB.get(job_key, "ANTHROPIC_MODEL_FAST")
        step["model"] = getattr(settings, model_setting_key)
        if run_job.started_at and run_job.finished_at:
            step["duration"] = _format_duration(int((run_job.finished_at - run_job.started_at).total_seconds()))
        # 🔴 2026-09-15 PE 신설 — RunJob에 배치 합계 토큰(input/output/캐시 생성/캐시
        # 읽기)이 쌓이는 자리가 생겨(services/runner.py _run_cleanup(), 모델 docstring
        # 참고) 여기서 그대로 읽는다. processed_count가 0이면(아직 한 건도 판정하지
        # 않았거나 전부 실패) 합계도 전부 0이라 의미 없는 "토큰 0"을 보여주지 않는다.
        if run_job.processed_count:
            total_tokens = (
                run_job.input_tokens + run_job.output_tokens
                + run_job.cache_creation_input_tokens + run_job.cache_read_input_tokens
            )
            step["tokens"] = f"{total_tokens:,}"
    review["step"] = step
    # 태그 제안의 target_type(기업 배지 색) 조회 — 제안마다 쿼리하지 않게 한 번에 모은다.
    org_type_by_name = dict(Organization.objects.values_list("name", "org_type"))

    delete_items = []
    retag_by_news = {}  # news_id 순서 보존(dict, 3.7+) — "같은 기사 행이 흩어지지 않게"
    tag_candidates = []
    keep_count = 0
    delete_news_ids = set()

    for p in proposals:
        if p.proposal_type == RunProposal.TYPE_DELETE:
            delete_news_ids.add(p.news_id)
            delete_items.append({
                "id": p.pk,
                "title": p.news.title,
                "published_at": p.news.published_at,
                "source": p.news.source_domain,
                "body_preview": _body_preview(p.news.body),
                "criterion_code": p.criterion_code,
                "criterion_label": CRITERION_LABELS.get(p.criterion_code, ""),
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
            })

    for news_id, group in retag_by_news.items():
        group["has_delete_proposal"] = news_id in delete_news_ids

    retag_groups = list(retag_by_news.values())

    review["delete_items"] = delete_items
    review["retag_groups"] = retag_groups
    # 🔴 2026-09-15 개정 — org_candidates에서 tag_candidates로 이름을 바꿨다(축 일반화).
    # 화면 쪽(templates/setting/run_review.html)도 함께 바뀌어야 한다 — PD 인계 사항.
    review["tag_candidates"] = tag_candidates

    # 🔴 2026-09-15 PE 신설 — 3단계(주요 이슈) 초안. RunProposal이 아니라 RunDraft에서
    # 온다(설계 3번 "산출물의 모양이 다르다"). insight_count는 None과 0을 구분해 내린다
    # — job_key가 "insight"가 아니면 아예 키를 만들지 않아 템플릿이 기존 정리 작업용
    # 문구(삭제·태그 교정·유지)로 떨어지고, "insight"인데 초안이 0건이면 정확히 0을
    # 내려 "새로 쓴 이슈 초안 0건"이 찍히게 한다.
    output = {
        "delete_count": len(delete_items),
        "retag_count": sum(len(g["items"]) for g in retag_groups),
        "keep_count": keep_count,
        # 🔴 커버리지·잠금 조건에 세지 않는다(run_review.html 상단 계약, design.md 4차
        # 개정 ⑩번) — OUTPUT 칸에만 별도로 찍는다. 이제 기업 후보뿐 아니라 기술 주제
        # 후보도 합산한 개수다.
        "candidate_count": len(tag_candidates),
        # 🔴 uncovered_count는 target_count - processed_count의 일반식을 그대로 쓴다.
        # cleanup은 이 식이 맞다(건별 판정이라 대상 전량에 제안이 있어야 한다). insight는
        # 아래에서 무조건 0으로 덮어쓴다 — 이유는 바로 아래 분기.
        "uncovered_count": max(run_job.target_count - run_job.processed_count, 0),
    }
    if job_key == "insight":
        insight_items = _insight_items_context(run_job)
        review["insight_items"] = insight_items
        output["insight_count"] = len(insight_items)
        output["draft_noun"] = RunDraft.TYPE_INSIGHT
        # 🔴 3단계는 배치 전체가 LLM 호출 1회다(설계 7-(a)) — "대상 전량에 제안이 있어야
        # 한다"는 커버리지 개념 자체가 이 단계에 없다(설계 PD 인계 3번). 위 일반식을 그대로
        # 쓰면 이슈로 묶이지 않고 남은 기사 수가 그대로 uncovered_count로 잡혀 확정 버튼이
        # 영영 잠긴다 — 이슈에 안 묶인 기사가 남는 것은 정상이다("입력 기사 전부를
        # 어딘가에 묶을 필요가 없다", services/llm.py _build_insight_system_prompt()).
        output["uncovered_count"] = 0
    elif job_key in ("weekly", "monthly"):
        # 🔴 같은 날 뒤이은 라운드 — 4, 5단계 보고서 초안. insight와 같은 이유로
        # RunProposal이 아니라 RunDraft에서 온다. insight_count 키를 그대로 쓰는 이유는
        # run_review.html 상단 계약 "output.insight_count" 주석 참고 — "세는 것이
        # '채택 대상 RunDraft 수'로 같아서 키를 늘리지 않았다."
        report_items = _report_items_context(run_job)
        review["report_items"] = report_items
        output["insight_count"] = len(report_items)
        output["draft_noun"] = RunDraft.TYPE_WEEKLY if job_key == "weekly" else RunDraft.TYPE_MONTHLY
        # 🔴 uncovered_count는 3단계와 같은 이유로 항상 0이다 — 대상 전량(그 기간의
        # Insight 전부)이 한 편의 보고서에 다 실릴 필요가 없다(상한 5건, 하한 없음).
        output["uncovered_count"] = 0
    review["output"] = output
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
    """SET-010 검토 화면(승인 게이트). 계약은 templates/setting/run_review.html 상단
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


def _confirm_insight_drafts(request, run_job) -> None:
    """SET-010 3단계(주요 이슈) 확정. 채택된 RunDraft마다 Insight를 만들어 근거
    News를 M2M으로 옮기고, 등급은 사람이 고른 값을 그대로 쓴다(설계 6번 표). 거절된
    초안은 지우지 않고 상태만 남긴다 — 거절 분포가 프롬프트 정확도를 잴 정답지라는
    원칙이 2단계와 같다.

    🔴 축약본(content_short/implication_short)은 비워 둔다 — RA가 채운다(모델
    default가 이미 빈 문자열이라 여기서 따로 손대지 않는다).
    🔴 headliner_order도 건드리지 않는다 — RA가 배치 단위로 전량 교체한다."""
    accepted_ids = set(request.POST.getlist("insight_ids"))
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


def _confirm_report_drafts(request, run_job) -> None:
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
            run_job=run_job, draft_type__in=(RunDraft.TYPE_WEEKLY, RunDraft.TYPE_MONTHLY),
            status=RunProposal.STATUS_PENDING,
        ).prefetch_related("news")
    )
    period_type = "weekly" if run_job.job_key == "weekly" else "monthly"

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
                draft.pk, run_job.job_key,
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

    처리 순서가 중요하다 — 삭제를 먼저 반영한 뒤 태그 교정을 처리한다. 같은 기사에
    삭제 제안과 태그 제안이 함께 있고 삭제가 채택되면, News 자체가 사라져 태그 교정의
    대상이 없어진다(run_review.html 상단 계약 "삭제가 채택되면 그 기사의 태그 교정은
    저절로 대상이 사라진다") — 그 경우 거절이 아니라 취소로 남긴다. 전제가 사라진
    것이지 사람이 틀렸다고 판단한 게 아니라서, 거절 분포(프롬프트 정확도 지표)를
    오염시키면 안 되기 때문이다.

    🔴 개별 삭제(delete_news_with_record), 태그 교정(correct_news_tag)은 각자 내부에서
    이미 트랜잭션으로 묶여 있다 — 이 뷰를 통째로 하나의 트랜잭션으로 다시 감싸지
    않는다. 감싸면 한 건이 실패했을 때 그 실패를 잡아도 같은 트랜잭션 안의 나머지
    쓰기까지 함께 위험해진다(Django가 트랜잭션을 "깨짐"으로 표시). 건별로 이미 원자적인
    헬퍼를 그대로 믿고, 건별 실패는 개별 try/except로만 잡아 건수를 센다."""
    if job not in RUN_JOB_KEYS:
        raise Http404

    run_job = RunJob.objects.filter(job_key=job).order_by("-started_at", "-pk").first()
    # 확정할 배치가 없거나, 이미 확정했거나, 아직 진행 중이거나 실패한 배치면 조용히
    # 실행 화면으로 돌려보낸다. 🔴 이 게이트가 "같은 배치를 두 번 확정할 수 없게" 만든다
    # — 이미 확정됨(STATUS_CONFIRMED)이면 여기서 걸려 재처리하지 않는다.
    if run_job is None or run_job.status not in (RunJob.STATUS_DONE, RunJob.STATUS_STOPPED):
        response = HttpResponse()
        response["HX-Redirect"] = reverse("setting_run")
        return response

    if job == "insight":
        # 🔴 3단계(주요 이슈)는 산출물의 모양이 달라(설계 3번) RunProposal이 아니라
        # RunDraft를 다룬다 — 아래 삭제/태그 교정 경로와 완전히 갈라진 별도 확정 경로다.
        _confirm_insight_drafts(request, run_job)
        run_job.status = RunJob.STATUS_CONFIRMED
        run_job.save(update_fields=["status"])
        response = HttpResponse()
        response["HX-Redirect"] = reverse("setting_run")
        return response

    if job in ("weekly", "monthly"):
        # 🔴 4, 5단계(주간·월간 보고서)도 insight와 같은 이유로 RunDraft를 다루는
        # 별도 확정 경로다.
        _confirm_report_drafts(request, run_job)
        run_job.status = RunJob.STATUS_CONFIRMED
        run_job.save(update_fields=["status"])
        response = HttpResponse()
        response["HX-Redirect"] = reverse("setting_run")
        return response

    accepted_delete_ids = set(request.POST.getlist("delete_ids"))
    accepted_retag_ids = set(request.POST.getlist("retag_ids"))

    pending = list(
        RunProposal.objects.filter(run_job=run_job, status=RunProposal.STATUS_PENDING)
        .select_related("news")
    )
    relevance_proposals = [p for p in pending if p.proposal_type in (RunProposal.TYPE_DELETE, RunProposal.TYPE_KEEP)]
    tag_proposals = [p for p in pending if p.proposal_type in (RunProposal.TYPE_TAG_ADD, RunProposal.TYPE_TAG_REMOVE)]
    candidate_proposals = [p for p in pending if p.proposal_type == RunProposal.TYPE_TAG_CANDIDATE]

    delete_failed = 0
    tag_not_found = 0  # 대상 이름을 이름/별칭 어느 쪽으로도 찾지 못한 경우
    tag_error = 0       # 대상은 찾았지만 correct_news_tag() 실행 자체가 실패한 경우
    deleted_news_ids = set()

    # ① 삭제/유지 — 태그 교정보다 먼저 처리한다(위 docstring 근거).
    for p in relevance_proposals:
        if p.proposal_type == RunProposal.TYPE_KEEP:
            # 유지는 체크박스가 없다 — 대기로 남아 있었다는 것 자체가 채택이다.
            p.news.status = News.STATUS_VERIFIED
            p.news.verified_at = timezone.now()
            p.news.save(update_fields=["status", "verified_at"])
            p.status = RunProposal.STATUS_ACCEPTED
            p.save(update_fields=["status"])
            continue

        if str(p.pk) not in accepted_delete_ids:
            p.status = RunProposal.STATUS_REJECTED
            p.save(update_fields=["status"])
            continue

        try:
            delete_news_with_record(
                p.news,
                criterion_code=p.criterion_code,
                reason=p.reason,
                judged_by=DeletedNewsRecord.JUDGED_BY_AUTO,
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

    # ② 태그 교정. 대상 조회는 collector의 별칭 매칭과 이름/별칭 비교 규칙을 그대로
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

    # ③ 태그 후보(기업 또는 기술 주제) — 아무 것도 실행하지 않는다(Organization·
    # TechTopic을 만들지 않는다). 채택도 거절도 아니라서 취소로 남긴다(design.md 4차
    # 개정 ⑩번 "후보 종류는 아무 것도 하지 않는다", 2026-09-15 축 일반화 이후에도
    # 그대로 상속되는 성질 — docs/planning.md 4-(b) 개정).
    for p in candidate_proposals:
        p.status = RunProposal.STATUS_CANCELED
        p.save(update_fields=["status"])

    run_job.status = RunJob.STATUS_CONFIRMED
    run_job.save(update_fields=["status"])

    if delete_failed or tag_not_found or tag_error:
        logger.warning(
            "RunJob %s(%s) 확정 중 삭제 실패 %d건, 태그 교정 대상 못 찾음 %d건, "
            "태그 교정 실행 실패 %d건이었어요.",
            run_job.pk, job, delete_failed, tag_not_found, tag_error,
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
    건드리지 않는다."""
    if job not in RUN_JOB_KEYS:
        raise Http404

    run_job = RunJob.objects.filter(job_key=job).order_by("-started_at", "-pk").first()
    if run_job is not None and run_job.status in (RunJob.STATUS_DONE, RunJob.STATUS_STOPPED):
        RunProposal.objects.filter(run_job=run_job, status=RunProposal.STATUS_PENDING).update(
            status=RunProposal.STATUS_CANCELED,
        )
        RunDraft.objects.filter(run_job=run_job, status=RunProposal.STATUS_PENDING).update(
            status=RunProposal.STATUS_CANCELED,
        )
        run_job.status = RunJob.STATUS_CANCELED
        run_job.save(update_fields=["status"])

    response = HttpResponse()
    response["HX-Redirect"] = reverse("setting_run")
    return response


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
        config.webhook_url = request.POST.get("webhook_url", "")
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


def logs(request):
    return render(request, "setting/logs.html", {
        "setting_menu": _setting_menu("logs"),
        "collection_logs": CollectionLog.objects.select_related("source").order_by("-started_at")[:50],
        "llm_logs": LLMLog.objects.select_related("news").order_by("-created_at")[:50],
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
    room.slack_webhook_url = request.POST.get("slack_webhook_url", "").strip()

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
