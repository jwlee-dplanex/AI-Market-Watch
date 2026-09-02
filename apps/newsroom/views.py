from django.core.paginator import Paginator
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, render

from .models import Newsroom, NewsroomArticle


def newsroom_list(request):
    """ROOM-001 — 읽기 전용 카드 그리드. 생성·수정 진입점은 두지 않는다(CUD는 SET-009
    전용, docs/design.md ROOM-001 절)."""
    return render(request, "newsroom/list.html", {"rooms": Newsroom.objects.all()})


def newsroom_detail(request, uid):
    """ROOM-002 — 날짜별 그룹 목록. 노출 게이트는 NewsroomArticleQuerySet.for_newsroom_display()
    하나로 모여 있다(5-1 예외 포함). 검색(`?q=`)은 반드시 그 게이트를 통과한 큐어리셋
    위에서만 걸어야 한다 — NewsroomArticle을 직접 조회해 필터링하면 미판정·제외 기사가
    검색 결과로 새어 나온다(2026-09-02, PD 지적)."""
    room = get_object_or_404(Newsroom, uid=uid)
    qs = (
        NewsroomArticle.objects
        .for_newsroom_display(room)
        .annotate(local_date=TruncDate("published_at"))
        .order_by("-published_at", "-pk")
    )

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(title__icontains=q)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    params = request.GET.copy()
    params.pop("page", None)
    base_query = params.urlencode()

    return render(request, "newsroom/detail.html", {
        "room": room,
        "articles": page_obj,
        "page_obj": page_obj,
        "is_paginated": paginator.num_pages > 1,
        "total_count": paginator.count,
        "q": q,
        "base_query": base_query,
    })
