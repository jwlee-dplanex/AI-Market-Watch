from django.core.paginator import Paginator
from django.db.models import Q
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


def _adjacent_article(room, article):
    """같은 뉴스룸, 같은 게이트(for_newsroom_display()) 안에서만 이전(더 최신)/
    다음(더 오래된) 기사를 찾는다(docs/design.md ROOM-003 절). 게이트 밖 기사로
    이동하면 목록에 없는 기사가 상세에 뜨는 모순이 생긴다. tie-breaker(pk) 포함
    — apps/news/views.py의 _adjacent_news()와 같은 이유(published_at 동률에서
    순서가 흔들리지 않게)."""
    qs = NewsroomArticle.objects.for_newsroom_display(room)
    prev_article = (
        qs.filter(Q(published_at__gt=article.published_at) |
                  Q(published_at=article.published_at, pk__gt=article.pk))
        .order_by("published_at", "pk")
        .only("uid", "title")
        .first()
    )
    next_article = (
        qs.filter(Q(published_at__lt=article.published_at) |
                  Q(published_at=article.published_at, pk__lt=article.pk))
        .order_by("-published_at", "-pk")
        .only("uid", "title")
        .first()
    )
    return prev_article, next_article


def newsroom_article_detail(request, room_uid, uid):
    """ROOM-003 — 뉴스룸 기사 상세(2026-09-02, 사용자 지시로 원문 새 창 대신 내부
    화면 추가). 노출 게이트는 ROOM-002와 완전히 같은 for_newsroom_display() 하나를
    공유한다 — 그 결과에 없는 기사(미판정·제외분, 5-1 예외가 닫힌 뒤)는 URL을 직접
    열어도 404다. 이 게이트를 빠뜨리면 목록에서 숨긴 의미가 없어진다."""
    room = get_object_or_404(Newsroom, uid=room_uid)
    article = get_object_or_404(NewsroomArticle.objects.for_newsroom_display(room), uid=uid)
    prev_article, next_article = _adjacent_article(room, article)
    return render(request, "newsroom/article_detail.html", {
        "room": room,
        "article": article,
        "prev_article": prev_article,
        "next_article": next_article,
    })
