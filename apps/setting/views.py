from django.db.models import Count, Min, Max, Exists, OuterRef
from django.http import Http404, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.news.models import News
from .models import (
    DataSource, Keyword, CollectionLog, LLMLog, SlackConfig,
    Organization, TechTopic, OrgRelation, RunJob,
)

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


@require_POST
def collect_now(request):
    from services.collector import run_collection
    # 실행 주체 = 수동(화면). CollectionLog는 run_collection() 진입점 안에서 남는다 — 여기서
    # 직접 CollectionLog.objects.create()를 부르지 않는다(docs/planning.md "수집 파이프라인
    # 관측성 정책" 2번 — 호출부에 로그 책임을 맡기지 않는 구조 결정).
    stats = run_collection(actor=CollectionLog.ACTOR_MANUAL)
    return render(request, "setting/_collect_result.html", {"stats": stats})


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


def _run_job_display(job_key):
    """job_key의 최신 RunJob으로 노드 표시값(state/state_label/summary/elapsed)을
    만든다. 그 job_key로 RunJob이 한 번도 없었으면 None을 반환한다 — 호출부가 기존
    방식(CollectionLog, NewsroomArticle.collected_at)으로 idle/done을 채운다.

    ⚠️ 'state'는 templates/setting/_run_node.html이 아는 값(idle/running/review/
    done/failed)만 써야 한다 — 그 템플릿은 PD 소관이라 이번 라운드에서 고치지
    않는다. RunJob.STATUS_STOPPED(중단됨)에 대응하는 전용 색이 아직 없어(PD 인계
    3번, docs/planning.md 10번 "PD 인계"), 잠정적으로 'failed'와 같은 배지 색을
    쓰되 state_label 텍스트로 실제 상태를 구분한다 — "색이 아니라 텍스트가
    정본"이라는 그 템플릿 자체의 원칙(43행 주석)을 그대로 따른 것이다."""
    run_job = RunJob.objects.filter(job_key=job_key).order_by("-started_at", "-pk").first()
    if not run_job:
        return None
    if run_job.status == RunJob.STATUS_RUNNING:
        seconds = int((timezone.now() - run_job.started_at).total_seconds())
        elapsed = f"{seconds // 60}분 {seconds % 60}초째" if seconds >= 60 else f"{seconds}초째"
        return {"state": "running", "state_label": "실행 중", "summary": "", "elapsed": elapsed}
    if run_job.status == RunJob.STATUS_STOPPED:
        return {
            "state": "failed",
            "state_label": "중단됨",
            "summary": f"{run_job.processed_count}/{run_job.target_count}건까지 처리하다 끊겼어요",
        }
    if run_job.status == RunJob.STATUS_FAILED:
        return {"state": "failed", "state_label": "실패", "summary": "실행이 실패했어요"}
    if run_job.status == RunJob.STATUS_DONE:
        return {
            "state": "done",
            "state_label": "완료",
            "summary": f"마지막 실행 {timezone.localtime(run_job.finished_at):%m/%d %H:%M} · {run_job.processed_count}건",
        }
    # 대기/확정됨/취소됨 — 이번 라운드의 collect/newsroom_collect는 여기 닿지 않는다
    # (승인 게이트가 없는 작업이라 확정·취소 상태로 가는 경로가 없다).
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
    for key in RESEARCH_JOB_KEYS[1:]:
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
    1단계 수집만 apps/newsroom/services.py의 collect_newsroom()을 실제로 부른다
    (SET-009의 "지금 수집" 버튼과 같은 함수를 공유하는 두 번째 진입점).
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
    # 나머지 여섯 단계 — services/llm.py가 비어 있어 아직 아무 일도 하지 않는다
    # (범위 밖). 노드 자체가 run_url 없이 비활성이라 UI에서는 여기로 POST가 오지
    # 않지만, 직접 호출되더라도 그래프를 안전하게 다시 그려 준다.
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


def setting_run_review(request, job):
    """SET-010 검토 화면(승인 게이트). 확정 대기 목록(RunProposal 가칭)이 아직 없으므로
    review 컨텍스트는 job_label/back_url만 채우고 나머지는 빈 상태로 정상 렌더된다
    (run_review.html 상단 계약 — "전부 없어도 화면은 빈 상태로 정상 렌더된다").

    🔴 이 화면이 검증 게이트의 네 번째 예외(docs/planning.md "검증 게이트" 2-(D),
    apps/news/models.py NewsQuerySet.verified() docstring)가 적용되는 자리다. 지금은
    보여줄 확정 대기 목록 자체가 없어 미검증 News를 실제로 조회하지 않지만, 1~4번
    구현 시에도 여기서는 News.objects.verified()가 아니라 미검증만 뽑는 별도 조회를
    써야 한다(verified()에 게이트를 끄는 옵션 인자를 뚫지 않는다)."""
    if job not in RUN_JOB_KEYS:
        raise Http404
    return render(request, "setting/run_review.html", {
        "setting_menu": _setting_menu("run"),
        "review": {
            "job_label": RUN_JOB_LABELS[job],
            "back_url": reverse("setting_run"),
            "confirm_url": "",
            "cancel_url": "",
        },
        "grade_choices": [],
    })


@require_POST
def setting_run_review_confirm(request, job):
    if job not in RUN_JOB_KEYS:
        raise Http404
    # 확정할 RunProposal이 아직 없다 — 화면 계약대로 실행 화면으로 돌려보낸다.
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


@require_POST
def setting_newsroom_collect(request, pk):
    from apps.newsroom.models import Newsroom
    from apps.newsroom.services import collect_newsroom
    room = get_object_or_404(Newsroom, pk=pk)
    stats = collect_newsroom(room)
    return render(request, "setting/_collect_result.html", {"stats": stats})


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
