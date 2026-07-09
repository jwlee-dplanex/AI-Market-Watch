from django.db.models import Count
from django.shortcuts import render

from apps.news.models import Insight, News


def dashboard(request):
    insights = (
        Insight.objects
        .annotate(news_count=Count("news"))
        .order_by("-created_at")[:5]
    )
    latest_news = News.objects.order_by("-published_at")[:10]

    return render(request, "dashboard/index.html", {
        "insights": insights,
        "latest_news": latest_news,
    })
