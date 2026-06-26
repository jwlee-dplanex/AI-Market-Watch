from django.shortcuts import render
from django.urls import reverse
from .models import DataSource, Keyword, Prompt, Schedule, CollectionLog, LLMLog, SlackConfig


def _setting_menu(active):
    items = [
        {"label": "데이터 소스", "icon": "database", "name": "setting_sources", "key": "sources"},
        {"label": "키워드", "icon": "tag", "name": "setting_keywords", "key": "keywords"},
        {"label": "프롬프트", "icon": "file-text", "name": "setting_prompts", "key": "prompts"},
        {"label": "스케줄", "icon": "clock", "name": "setting_schedule", "key": "schedule"},
        {"label": "Slack", "icon": "slack", "name": "setting_slack", "key": "slack"},
        {"label": "로그", "icon": "scroll-text", "name": "setting_logs", "key": "logs"},
    ]
    for item in items:
        item["url"] = reverse(item["name"])
        item["active"] = item["key"] == active
    return items


def sources(request):
    return render(request, "setting/sources.html", {
        "setting_menu": _setting_menu("sources"),
        "sources": DataSource.objects.all(),
    })


def keywords(request):
    return render(request, "setting/keywords.html", {
        "setting_menu": _setting_menu("keywords"),
        "collect_keywords": Keyword.objects.filter(keyword_type=Keyword.TYPE_COLLECT),
        "exclude_keywords": Keyword.objects.filter(keyword_type=Keyword.TYPE_EXCLUDE),
    })


def prompts(request):
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
