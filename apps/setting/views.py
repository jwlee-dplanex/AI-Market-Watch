from django.db.models import Count, Min, Max, Exists, OuterRef
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.news.models import News
from .models import (
    DataSource, Keyword, Prompt, Schedule, CollectionLog, LLMLog, SlackConfig,
    Organization, TechTopic, OrgRelation,
)

# SET-006 검증 파이프라인 현황 "stale" 임계값(일). PD 판단값이며 고정 정책이 아니다
# (docs/design.md SET-006 절 — 임계값 조정 시 이 상수만 바꾸면 된다).
UNVERIFIED_STALE_DAYS = 2


def _setting_menu(active):
    items = [
        {"label": "데이터 소스", "icon": "database",      "name": "setting_sources",       "key": "sources"},
        {"label": "키워드",     "icon": "tag",            "name": "setting_keywords",      "key": "keywords"},
        {"label": "기업",       "icon": "building-2",     "name": "setting_organizations", "key": "organizations"},
        {"label": "기술 주제",  "icon": "cpu",            "name": "setting_tech_topics",   "key": "tech_topics"},
        {"label": "프롬프트",   "icon": "file-text",      "name": "setting_prompts",       "key": "prompts"},
        {"label": "스케줄",     "icon": "clock",          "name": "setting_schedule",      "key": "schedule"},
        {"label": "Slack",      "icon": "slack",          "name": "setting_slack",         "key": "slack"},
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


def prompts(request):
    if request.method == "POST":
        prompt_id = request.POST.get("prompt_id")
        content = request.POST.get("content", "")
        from django.utils.timezone import now
        Prompt.objects.filter(pk=prompt_id).update(content=content, updated_at=now())
        return redirect("setting_prompts")
    return render(request, "setting/prompts.html", {
        "setting_menu": _setting_menu("prompts"),
        "prompts": Prompt.objects.all(),
    })


def schedule(request):
    return render(request, "setting/schedule.html", {
        "setting_menu": _setting_menu("schedule"),
        **_schedule_context(),
    })


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


def _schedule_context():
    """SET-004(스케줄 관리) 공통 컨텍스트. schedule()(전체 화면)과 schedule_save/toggle/delete
    (HTMX 프래그먼트 _schedule_list.html)가 이 함수 하나를 공유한다 — 예전엔 schedule()이 이 함수를
    안 쓰고 자체적으로 Schedule.objects.all()을 조회해 정렬·부가 데이터가 어긋날 수 있었다.

    각 Schedule 객체에 is_registered(실제로 스케줄러 잡이 걸려 있는가)를 얹는다. is_active(사용자
    의도)와 별개 값으로 내려준다 — 두 값이 어긋나면 그 자체가 경보라는 것이 관측성 정책의 핵심이다
    (docs/planning.md "수집 파이프라인 관측성 정책" 3-(c)). 표시 방식은 PD 몫이며 여기서는 값만
    준비한다."""
    from services import scheduler
    schedules = list(Schedule.objects.all().order_by("schedule_type"))
    for sched in schedules:
        sched.is_registered = scheduler.is_registered(sched.pk)
    return {"schedules": schedules}


@require_POST
def schedule_save(request):
    from apscheduler.triggers.cron import CronTrigger
    pk = request.POST.get("pk", "").strip()
    stype = request.POST.get("schedule_type", "")
    cron_expr = request.POST.get("cron_expr", "").strip()
    is_active = request.POST.get("is_active") == "on"

    try:
        CronTrigger.from_crontab(cron_expr)
    except Exception:
        return render(request, "setting/_schedule_list.html",
                      {**_schedule_context(), "error": f"잘못된 cron 표현식: {cron_expr}"})

    if pk:
        sched = get_object_or_404(Schedule, pk=pk)
        sched.schedule_type = stype
        sched.cron_expr = cron_expr
        sched.is_active = is_active
        sched.save()
    else:
        sched = Schedule.objects.create(
            schedule_type=stype, cron_expr=cron_expr, is_active=is_active
        )

    from services import scheduler
    if sched.is_active:
        scheduler.register(sched)
    else:
        scheduler.unregister(sched.pk)

    return render(request, "setting/_schedule_list.html", _schedule_context())


@require_POST
def schedule_toggle(request, pk):
    sched = get_object_or_404(Schedule, pk=pk)
    sched.is_active = not sched.is_active
    sched.save()

    from services import scheduler
    if sched.is_active:
        scheduler.register(sched)
    else:
        scheduler.unregister(sched.pk)

    return render(request, "setting/_schedule_list.html", _schedule_context())


@require_POST
def schedule_delete(request, pk):
    sched = get_object_or_404(Schedule, pk=pk)
    from services import scheduler
    scheduler.unregister(sched.pk)
    sched.delete()
    return render(request, "setting/_schedule_list.html", _schedule_context())


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
