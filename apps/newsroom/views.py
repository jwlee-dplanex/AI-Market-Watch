from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect, render

from .models import Newsroom, NewsroomArticle

# ROOM-002 세 층 대시보드(docs/design.md ROOM-002 절, 2026-09-04) — PD 권장 자름 건수.
HEADLINE_LIMIT = 5

# 관계사 4칸(교보생명/교보증권/교보문고/교보 라이프플래닛) 층은 2026-09-08에 제거됐다
# (docs/design.md ROOM-002 절 "층 구조" 참고). 관계사 태그는 이제 NewsroomAffiliate
# 모델(apps/newsroom/models.py)로 옮겨 기사 카드 배지로만 노출한다 — 여기 있던
# AFFILIATE_GROUP_KEYWORDS 모듈 상수(다중 채널을 막던 원인)와 affiliate_groups
# 컨텍스트는 함께 걷어냈다.


def newsroom_list(request):
    """ROOM-001 — 읽기 전용 카드 그리드. 생성·수정 진입점은 두지 않는다(CUD는 SET-009
    전용, docs/design.md ROOM-001 절).

    PM 정책(2026-09-04): 활성 뉴스룸이 1개면 이 목록을 건너뛰고 그 뉴스룸(ROOM-002)으로
    직행한다. 사이드바 링크(apps/newsroom/context_processors.py newsroom_nav)가 이미
    같은 조건으로 ROOM-002를 바로 가리키지만, 이 리다이렉트는 URL을 직접 치거나
    북마크로 들어온 경우까지 규칙을 지키기 위한 보완이다(둘은 대체재가 아니다,
    docs/design.md 참고)."""
    rooms = list(Newsroom.objects.all())
    active_rooms = [r for r in rooms if r.is_active]
    if len(active_rooms) == 1:
        return redirect("newsroom_detail", uid=active_rooms[0].uid)
    return render(request, "newsroom/list.html", {"rooms": rooms})


def newsroom_detail(request, uid):
    """ROOM-002 — 헤드라인 / 전체 목록 두 층 대시보드(2026-09-08, 관계사별 층은 제거됨.
    docs/design.md ROOM-002 절 참고) + 날짜별 그룹 목록. 노출 게이트는
    NewsroomArticleQuerySet.for_newsroom_display() 하나로 모여 있다(5-1 예외 포함) —
    두 층 전부 이 게이트를 거친 큐어리셋 위에서만 만든다. 직접 NewsroomArticle을
    조회해 만들면 미판정·제외 기사가 대시보드 최상단으로 샌다(templates/newsroom/
    detail.html PE 인계 절 경고).

    검색(`?q=`) 중에는 ①②를 만들지 않는다 — "검색은 전체에서 찾기라 섹션 구조가
    방해된다"(템플릿 계약). ①②의 기사는 ③에도 그대로 나온다(중복 허용, 템플릿이
    이미 그렇게 설계됨)."""
    room = get_object_or_404(Newsroom, uid=uid)
    base_qs = NewsroomArticle.objects.for_newsroom_display(room).prefetch_related("affiliates")
    qs = (
        base_qs
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

    context = {
        "room": room,
        "articles": page_obj,
        "page_obj": page_obj,
        "is_paginated": paginator.num_pages > 1,
        "total_count": paginator.count,
        "q": q,
        "base_query": base_query,
    }

    if not q:
        context["headline_articles"] = list(
            base_qs.filter(is_ai_related=True).order_by("-published_at", "-pk")[:HEADLINE_LIMIT]
        )

    return render(request, "newsroom/detail.html", context)


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
