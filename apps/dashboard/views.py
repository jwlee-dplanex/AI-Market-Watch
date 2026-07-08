from django.db.models import Count
from django.shortcuts import render

from apps.news.models import IssueGroup, News


def dashboard(request):
    issue_groups = (
        IssueGroup.objects
        .annotate(news_count=Count("issuegroupnews"))
        .order_by("-created_at")[:5]
    )
    latest_news = News.objects.filter(is_relevant=True).order_by("-published_at")[:10]

    return render(request, "dashboard/index.html", {
        "issue_groups": issue_groups,
        "latest_news": latest_news,
    })
