from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from .models import News, IssueGroup


CATEGORIES = [
    ("기술흐름", "기술흐름"),
    ("기업사례", "기업사례"),
    ("금융권활용", "금융권활용"),
    ("규제·정책", "규제·정책"),
    ("경쟁사동향", "경쟁사동향"),
]


def news_list(request):
    qs = News.objects.order_by("-published_at")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(title__icontains=q)

    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    if date_from:
        qs = qs.filter(published_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(published_at__date__lte=date_to)

    categories = request.GET.getlist("category")
    if categories:
        qs = qs.filter(category__in=categories)

    source = request.GET.get("source", "")
    if source:
        qs = qs.filter(source_type=source)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "news/list.html", {
        "news_list": page_obj,
        "page_obj": page_obj,
        "is_paginated": paginator.num_pages > 1,
        "total_count": paginator.count,
        "categories": CATEGORIES,
        "selected_categories": categories,
    })


def news_detail(request, pk):
    news = get_object_or_404(News, pk=pk)

    insights = []
    issue_group = news.issuegroupnews_set.select_related("issue_group").first()
    if issue_group:
        insights = issue_group.issue_group.insights.all()

    similar_news = []
    if hasattr(news, "embedding"):
        from pgvector.django import CosineDistance
        similar_news = (
            News.objects
            .alias(dist=CosineDistance("embedding__vector", news.embedding.vector))
            .filter(dist__lte=0.18)
            .exclude(pk=pk)
            .order_by("dist")[:5]
        )

    return render(request, "news/detail.html", {
        "news": news,
        "insights": insights,
        "similar_news": similar_news,
    })
