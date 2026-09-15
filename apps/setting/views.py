import logging

from django.contrib import messages
from django.db.models import Count, Min, Max, Exists, OuterRef
from django.http import Http404, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.news.models import DeletedNewsRecord, News, TagCorrectionRecord
from apps.news.services import correct_news_tag, delete_news_with_record
from .models import (
    DataSource, Keyword, CollectionLog, LLMLog, SlackConfig,
    Organization, TechTopic, OrgRelation, RunJob, RunProposal,
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
# — 그 둘은 STATUS_DONE이 곧 "더 할 일 없음"이다. 2라운드는 cleanup만 구현됐다.
GATED_JOB_KEYS = ("cleanup",)

# SET-010 검토 화면(run_review.html) 판정 기준 코드 범례. services/llm.py의
# SYSTEM_PROMPT가 내는 criterion_code enum(1-a/1-b/3/4/5/6/S-KLS/기타)과 값·순서를
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
        if job_key in GATED_JOB_KEYS:
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
        return {"state": state, "state_label": state_label, "summary": "", "elapsed": elapsed}
    if state == "stopped":
        return {
            "state": state, "state_label": state_label,
            "summary": f"{run_job.processed_count}/{run_job.target_count}건까지 처리하다 끊겼어요",
        }
    if state == "failed":
        return {"state": state, "state_label": state_label, "summary": "실행이 실패했어요"}
    if state == "review":
        return {
            "state": state, "state_label": state_label,
            "summary": f"{run_job.processed_count}건 판정을 마쳤어요, 검토를 기다리고 있어요",
        }
    if run_job.status == RunJob.STATUS_DONE:
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

    for key in RESEARCH_JOB_KEYS[2:]:
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
    # 나머지 여섯 단계(insight/weekly/monthly, 뉴스룸 2~4단계) — services/llm.py의
    # 판정 로직은 지금 cleanup 하나만 쓴다. 노드 자체가 run_url 없이 비활성이라
    # UI에서는 여기로 POST가 오지 않지만, 직접 호출되더라도 그래프를 안전하게 다시
    # 그려 준다.
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
        # "모두 취소"(제안 폐기)는 이번 라운드 범위 밖이다 — setting_run_review_cancel이
        # 아직 실제로 아무 것도 취소하지 않는 스텁이라, URL을 비워 템플릿이 버튼 자체를
        # 감추게 한다(run_review.html 상단 계약 "cancel_url 비어 있으면 버튼을 감춘다").
        "cancel_url": "",
        "org_admin_url": reverse("setting_organizations"),
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
            f"{run_job.target_count}건 중 {run_job.processed_count}건 처리" if run_job.target_count else ""
        ),
        "failed_str": f"실패 {run_job.failed_count}건" if run_job.failed_count else "",
        "resumable": state == "stopped",
    }
    review["step"] = {"prompt_version": run_job.prompt_version}

    proposals = list(
        RunProposal.objects.filter(run_job=run_job, status=RunProposal.STATUS_PENDING)
        .select_related("news")
        .order_by("-news__published_at", "news_id", "pk")
    )
    # 태그 제안의 target_type(기업 배지 색) 조회 — 제안마다 쿼리하지 않게 한 번에 모은다.
    org_type_by_name = dict(Organization.objects.values_list("name", "org_type"))

    delete_items = []
    retag_by_news = {}  # news_id 순서 보존(dict, 3.7+) — "같은 기사 행이 흩어지지 않게"
    org_candidates = []
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
        elif p.proposal_type == RunProposal.TYPE_ORG_CANDIDATE:
            org_candidates.append({
                "name": p.target_name,
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
    review["org_candidates"] = org_candidates
    review["output"] = {
        "delete_count": len(delete_items),
        "retag_count": sum(len(g["items"]) for g in retag_groups),
        "keep_count": keep_count,
        # 🔴 커버리지·잠금 조건에 세지 않는다(run_review.html 상단 계약, design.md 4차
        # 개정 ⑩번) — OUTPUT 칸에만 별도로 찍는다.
        "candidate_count": len(org_candidates),
        "insight_count": 0,  # 3단계(주요 이슈)는 이번 라운드 범위 밖 — RunProposal에 해당 종류가 없다.
        "uncovered_count": max(run_job.target_count - run_job.processed_count, 0),
    }
    return review


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
        "grade_choices": [],
    })


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

    accepted_delete_ids = set(request.POST.getlist("delete_ids"))
    accepted_retag_ids = set(request.POST.getlist("retag_ids"))

    pending = list(
        RunProposal.objects.filter(run_job=run_job, status=RunProposal.STATUS_PENDING)
        .select_related("news")
    )
    relevance_proposals = [p for p in pending if p.proposal_type in (RunProposal.TYPE_DELETE, RunProposal.TYPE_KEEP)]
    tag_proposals = [p for p in pending if p.proposal_type in (RunProposal.TYPE_TAG_ADD, RunProposal.TYPE_TAG_REMOVE)]
    candidate_proposals = [p for p in pending if p.proposal_type == RunProposal.TYPE_ORG_CANDIDATE]

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

    # ③ 기업 후보 — 아무 것도 실행하지 않는다(Organization을 만들지 않는다). 채택도
    # 거절도 아니라서 취소로 남긴다(design.md 4차 개정 ⑩번 "기업 후보 종류는 아무 것도
    # 하지 않는다").
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
    if job not in RUN_JOB_KEYS:
        raise Http404
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
