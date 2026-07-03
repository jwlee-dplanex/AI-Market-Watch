from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from .models import DataSource, Keyword, Prompt, Schedule, CollectionLog, LLMLog, SlackConfig, Organization


def _setting_menu(active):
    items = [
        {"label": "데이터 소스", "icon": "database",      "name": "setting_sources",       "key": "sources"},
        {"label": "키워드",     "icon": "tag",            "name": "setting_keywords",      "key": "keywords"},
        {"label": "기관",       "icon": "building-2",     "name": "setting_organizations", "key": "organizations"},
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
    from services.collector import collect_naver
    stats = collect_naver()
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
def keyword_add(request):
    keyword      = request.POST.get("keyword", "").strip()
    keyword_type = request.POST.get("keyword_type", Keyword.TYPE_COLLECT)
    sort         = request.POST.get("sort", Keyword.SORT_DATE)
    if keyword:
        Keyword.objects.get_or_create(
            keyword=keyword,
            keyword_type=keyword_type,
            defaults={"sort": sort},
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
        "schedules": Schedule.objects.all(),
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


def logs(request):
    return render(request, "setting/logs.html", {
        "setting_menu": _setting_menu("logs"),
        "collection_logs": CollectionLog.objects.select_related("source").order_by("-started_at")[:50],
        "llm_logs": LLMLog.objects.select_related("news").order_by("-created_at")[:50],
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


def _schedule_context():
    return {"schedules": Schedule.objects.all().order_by("schedule_type")}


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
    return render(request, "setting/_remap_result.html", {"remap_count": count})
