from django.db.models import Q
from django.db.models.functions import TruncDate
from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
from .models import ExcludedURL, News


ORG_TYPES = [
    ("금융사", "금융사"),
    ("보험사", "보험사"),
    ("AI",    "AI"),
    ("기타",  "기업 없음"),
]


def news_list(request):
    order = request.GET.get("order", "newest")
    order_fields = ("published_at", "pk") if order == "oldest" else ("-published_at", "-pk")
    # 검증 게이트(docs/planning.md): NEWS-001 목록·total_count는 직접 조회 경로이므로
    # 검증분만 노출한다.
    qs = (
        News.objects
        .verified()
        .prefetch_related("organizations")
        .annotate(local_date=TruncDate("published_at"))
        .order_by(*order_fields)
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
        "org_types": ORG_TYPES,
        "org_type_filter": org_type,
        "order": order,
        "base_query": base_query,
    })


def _adjacent_news(news):
    """최신순(News.Meta.ordering) 기준 이전(더 최신)/다음(더 오래된) 뉴스.
    검증 게이트: 이전/다음 이동도 검증분 안에서만 움직인다 — 그렇지 않으면 목록에는
    없는 미검증 뉴스로 이동하는 경로가 생긴다."""
    prev_news = (
        News.objects
        .verified()
        .filter(Q(published_at__gt=news.published_at) |
                Q(published_at=news.published_at, pk__gt=news.pk))
        .order_by("published_at", "pk")
        .only("uid", "title")
        .first()
    )
    next_news = (
        News.objects
        .verified()
        .filter(Q(published_at__lt=news.published_at) |
                Q(published_at=news.published_at, pk__lt=news.pk))
        .order_by("-published_at", "-pk")
        .only("uid", "title")
        .first()
    )
    return prev_news, next_news


def news_detail(request, uid):
    from apps.setting.models import Organization
    # 검증 게이트: 미검증 뉴스는 URL 직접 접근 시 404. 목록에서 숨기는 의미가 없어지므로
    # 상세도 반드시 게이트를 공유한다.
    news = get_object_or_404(News.objects.verified(), uid=uid)

    insights = news.insights.all()

    linked_orgs = news.organizations.all()
    all_orgs = Organization.objects.filter(is_active=True).exclude(pk__in=linked_orgs)

    prev_news, next_news = _adjacent_news(news)

    return render(request, "news/detail.html", {
        "news": news,
        "insights": insights,
        "linked_orgs": linked_orgs,
        "all_orgs": all_orgs,
        "prev_news": prev_news,
        "next_news": next_news,
    })


@require_POST
def news_delete(request, uid):
    news = get_object_or_404(News, uid=uid)
    source = request.POST.get("source", "list")
    next_news = _adjacent_news(news)[1] if source == "detail" else None

    ExcludedURL.objects.get_or_create(url_hash=news.url_hash)
    news.delete()

    response = HttpResponse()
    if source == "detail":
        target = reverse("news_detail", args=[next_news.uid]) if next_news else reverse("news_list")
        response["HX-Redirect"] = target
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
