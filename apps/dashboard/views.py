import datetime
from collections import Counter

from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone

from apps.news.models import IssueGroup, News


def dashboard(request):
    today = timezone.localdate()
    two_weeks_ago = today - datetime.timedelta(days=13)

    issue_groups = (
        IssueGroup.objects
        .annotate(news_count=Count("issuegroupnews"))
        .order_by("-created_at")[:5]
    )
    latest_news = News.objects.order_by("-published_at")[:10]

    daily_qs = (
        News.objects
        .filter(collected_at__date__gte=two_weeks_ago)
        .values("collected_at__date")
        .annotate(count=Count("id"))
        .order_by("collected_at__date")
    )
    date_map = {r["collected_at__date"]: r["count"] for r in daily_qs}
    chart_daily = [
        {
            "date": (two_weeks_ago + datetime.timedelta(days=i)).strftime("%m/%d"),
            "count": date_map.get(two_weeks_ago + datetime.timedelta(days=i), 0),
        }
        for i in range(14)
    ]

    tag_counter = Counter()
    for tags in News.objects.exclude(tags={}).values_list("tags", flat=True):
        if isinstance(tags, dict):
            for vals in tags.values():
                if isinstance(vals, list):
                    tag_counter.update(vals)
    chart_tags = [{"tag": t, "count": c} for t, c in tag_counter.most_common(10)]

    return render(request, "dashboard/index.html", {
        "issue_groups": issue_groups,
        "latest_news": latest_news,
        "chart_daily": chart_daily,
        "chart_tags": chart_tags,
    })
