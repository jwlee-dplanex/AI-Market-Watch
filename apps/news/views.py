from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
from .models import News, IssueGroup


CATEGORIES = [
    ("기술흐름", "기술흐름"),
    ("기업사례", "기업사례"),
    ("금융권활용", "금융권활용"),
    ("규제·정책", "규제·정책"),
    ("경쟁사동향", "경쟁사동향"),
]

ORG_TYPES = [
    ("금융사", "금융사"),
    ("보험사", "보험사"),
    ("AI",    "AI"),
    ("기타",  "기관 없음"),
]


def news_list(request):
    order = request.GET.get("order", "newest")
    qs = News.objects.prefetch_related("organizations").order_by(
        "published_at" if order == "oldest" else "-published_at"
    )

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

    org_type = request.GET.get("org_type", "")
    if org_type == "기타":
        qs = qs.filter(organizations__isnull=True)
    elif org_type:
        qs = qs.filter(organizations__org_type=org_type, organizations__is_active=True).distinct()

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    params = request.GET.copy()
    params.pop("page", None)
    base_query = params.urlencode()

    return render(request, "news/list.html", {
        "news_list": page_obj,
        "page_obj": page_obj,
        "is_paginated": paginator.num_pages > 1,
        "total_count": paginator.count,
        "categories": CATEGORIES,
        "selected_categories": categories,
        "org_types": ORG_TYPES,
        "org_type_filter": org_type,
        "order": order,
        "base_query": base_query,
    })


def news_detail(request, uid):
    from apps.setting.models import Organization
    news = get_object_or_404(News, uid=uid)

    insights = []
    issue_group = news.issuegroupnews_set.select_related("issue_group").first()
    if issue_group:
        insights = issue_group.issue_group.insights.all()

    similar_news = []
    if hasattr(news, "embedding"):
        from django.conf import settings
        from pgvector.django import CosineDistance
        threshold = 1 - settings.EMBEDDING_SIMILARITY_THRESHOLD
        similar_news = (
            News.objects
            .alias(dist=CosineDistance("embedding__vector", news.embedding.vector))
            .filter(dist__lte=threshold)
            .exclude(pk=news.pk)
            .order_by("dist")[:5]
        )

    linked_orgs = news.organizations.all()
    all_orgs = Organization.objects.filter(is_active=True).exclude(pk__in=linked_orgs)

    return render(request, "news/detail.html", {
        "news": news,
        "insights": insights,
        "similar_news": similar_news,
        "linked_orgs": linked_orgs,
        "all_orgs": all_orgs,
    })


@require_POST
def news_delete(request, uid):
    news = get_object_or_404(News, uid=uid)
    news.delete()
    source = request.POST.get("source", "list")
    response = HttpResponse()
    if source == "detail":
        response["HX-Redirect"] = reverse("news_list")
    return response


@require_POST
def news_org_add(request, uid):
    news = get_object_or_404(News, uid=uid)
    from apps.setting.models import Organization
    org_pk = request.POST.get("org_pk")
    if org_pk:
        try:
            org = Organization.objects.get(pk=org_pk, is_active=True)
            news.organizations.add(org)
        except Organization.DoesNotExist:
            pass
    linked_orgs = news.organizations.all()
    all_orgs = Organization.objects.filter(is_active=True).exclude(pk__in=linked_orgs)
    return render(request, "news/_orgs.html", {"news": news, "linked_orgs": linked_orgs, "all_orgs": all_orgs})


@require_POST
def news_org_remove(request, uid, org_pk):
    news = get_object_or_404(News, uid=uid)
    from apps.setting.models import Organization
    try:
        org = Organization.objects.get(pk=org_pk)
        news.organizations.remove(org)
    except Organization.DoesNotExist:
        pass
    linked_orgs = news.organizations.all()
    all_orgs = Organization.objects.filter(is_active=True).exclude(pk__in=linked_orgs)
    return render(request, "news/_orgs.html", {"news": news, "linked_orgs": linked_orgs, "all_orgs": all_orgs})
