from django.contrib import messages
from django.db.models import Q
from django.db.models.functions import TruncDate
from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
from .models import DeletedNewsRecord, News, TagCorrectionRecord
from .services import correct_news_tag, delete_news_with_record, has_explicit_link


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
    #
    # 🔴 2026-09-17 — .verified()를 그대로 쓰지 않는다. verified()는 (E) 조건으로
    # duplicate_of가 채워진 News(중복 묶음의 대표 아닌 나머지)까지 함께 제외하는데,
    # 그 News는 Insight.news/Report.news 근거 목록·report_extras의 "참고: <uid>"
    # 해석 경로((B) 예외, verified()를 안 거침)에서는 그대로 링크로 노출된다. 즉
    # "근거로는 보여주면서 클릭하면 404"가 되는 모순이 생긴다. 미검증(status)은 계속
    # 404여야 하지만, 중복은 이미 검증을 마친 정당한 근거이므로 상세는 열어 준다 —
    # 상태 게이트만 걸고 duplicate_of 조건은 걸지 않는다.
    news = get_object_or_404(
        News.objects.select_related("duplicate_of"),
        uid=uid,
        status=News.STATUS_VERIFIED,
    )

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

    # 🔴 삭제 금지 셋 방어 (2026-09-17 신설, 사용자 확정). apps/news/services.py의
    # has_explicit_link() docstring이 "이 헬퍼가 True를 반환하는 News는 **어떤 삭제
    # 경로에서도** 지워지면 안 된다"고 적어 뒀는데, 실제로는 services/runner.py의
    # 중복 판정 한 곳에만 배선돼 있었다. 이 화면 버튼이 그 계약 밖에 있었다.
    #
    # 실측(2026-09-17): Insight에 연결된 News(pk=4120, 그 Insight의 근거 9건)를 이
    # 경로로 지우면 실제로 지워지고 Insight.news가 9→8건으로 줄었다. 시사점 본문은
    # 그대로 남는데 근거만 사라지므로, 화면은 멀쩡해 보이고 출처 추적만 끊긴다.
    # 같은 사고가 이미 두 번 났다(OrgRelation pk79·pk66, 2026-09-17 오전).
    #
    # 🔴 delete_news_with_record() 안이 아니라 여기에 둔다. 그 헬퍼는 2단계 확정
    # 경로(apps/setting/views.py)도 함께 쓰는데, 3단계가 먼저 돈 날은 그 배치의
    # 기사가 전부 Insight에 걸려 있어(9/17 수집분 23건 전량이 그랬다) 헬퍼에 넣으면
    # 2단계가 아무것도 확정하지 못한다. 자동 경로는 _run_dedup()이 이미 이 함수로
    # 방어하고 있으므로, 막을 곳은 사람이 사유 없이 누르는 이 버튼 하나다.
    #
    # ⚠️ HX-Reswap이나 상태 코드만으로는 사람에게 아무것도 안 보인다 — 행이 그대로
    # 남아서 "눌렀는데 아무 일도 안 났다"가 된다. base.html 알림 배너가 뜨도록 원래
    # 있던 화면으로 되돌린다(지우지 않았으므로 상세도 그대로 열린다).
    if has_explicit_link(news):
        messages.error(
            request,
            "이 기사는 시사점이나 보고서, 지식 그래프 관계의 근거로 쓰이고 있어서 "
            "지울 수 없어요. 먼저 그 연결을 정리해 주세요.",
        )
        response = HttpResponse()
        response["HX-Redirect"] = (
            reverse("news_detail", args=[news.uid]) if source == "detail"
            else reverse("news_list")
        )
        return response

    # 판정 기록 보존 정책(docs/planning.md, 2026-08-04): 기록 없는 삭제 경로를 남기지
    # 않기 위해 헬퍼를 거친다. 화면 삭제는 사유 입력 UI가 없으므로 기준·사유는 빈 값.
    delete_news_with_record(news, judged_by=DeletedNewsRecord.JUDGED_BY_USER)

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
            # 판정 기록 보존 정책 4번(P1, docs/planning.md): 태깅 교정도 기록 없는
            # 경로를 남기지 않는다. 화면 조작은 사유 입력 UI가 없으므로 사유는 빈 값.
            correct_news_tag(
                news, org,
                action=TagCorrectionRecord.ACTION_ADD,
                judged_by=TagCorrectionRecord.JUDGED_BY_USER,
            )
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
        correct_news_tag(
            news, org,
            action=TagCorrectionRecord.ACTION_REMOVE,
            judged_by=TagCorrectionRecord.JUDGED_BY_USER,
        )
    except Organization.DoesNotExist:
        pass
    linked_orgs = news.organizations.all()
    all_orgs = Organization.objects.filter(is_active=True).exclude(pk__in=linked_orgs)
    return render(request, "news/_orgs.html", {"news": news, "linked_orgs": linked_orgs, "all_orgs": all_orgs})
