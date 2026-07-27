from itertools import combinations
from collections import defaultdict

from django.http import Http404
from django.shortcuts import render, get_object_or_404
from django.db.models import Count, Q
from django.utils import timezone

from apps.setting.models import Organization
from apps.news.models import News
from services.periods import period_bounds, resolve_period

CATEGORY_INDEX = {"금융사": 0, "보험사": 1, "AI": 2}

# 금융사·보험사는 AI 기업과의 연결만 허용 (금융사-금융사, 금융사-보험사, 보험사-보험사, AI-AI 연결 제외)
ALLOWED_TYPE_PAIRS = {frozenset({"금융사", "AI"}), frozenset({"보험사", "AI"})}


def _edge_allowed(type_a, type_b):
    return frozenset({type_a, type_b}) in ALLOWED_TYPE_PAIRS


# --- 공통 기간 필터 헬퍼 (graph, graph_org_panel, graph_edge_panel 공유 — 기간 정합성 계약) ---
# 기준 필드는 News.published_at(발행일). collected_at이 아님. 파싱/경계 계산 자체는
# services/periods.py(대시보드 앱과 공유)에 있고, 여기 남은 건 News/Organization 쿼리셋에
# 그 경계를 적용하는 그래프 앱 전용 얇은 래퍼뿐이다.

def _apply_period_filter(news_qs, start_date, today):
    """News 쿼리셋에 published_at 기준 기간 필터를 적용. start_date가 None이면 "전체" —
    필터를 아예 걸지 않는다(services.periods.period_bounds 계약)."""
    if start_date is None:
        return news_qs
    return news_qs.filter(published_at__date__gte=start_date, published_at__date__lte=today)


def _period_news_count(start_date, today):
    """Organization.annotate(news_count=...)에 쓰는 조건부 Count.
    그냥 .filter()를 annotate 앞에 걸면 JOIN 자체가 필터링돼 다른 집계에 영향을 줄 수 있어
    반드시 Count(..., filter=Q(...)) 형태로 조건부 집계해야 한다."""
    if start_date is None:
        return Count("news")
    return Count(
        "news",
        filter=Q(news__published_at__date__gte=start_date, news__published_at__date__lte=today),
    )


def graph(request):
    period = resolve_period(request)
    today = timezone.localtime(timezone.now()).date()
    start_date, today = period_bounds(period, today)

    orgs = list(
        Organization.objects.filter(is_active=True)
        .annotate(news_count=_period_news_count(start_date, today))
        .filter(news_count__gt=0)
    )

    nodes = [
        {
            "id": str(o.pk),
            "name": o.name,
            "category": CATEGORY_INDEX.get(o.org_type, 0),
            "symbolSize": max(14, min(40, 14 + o.news_count * 2)),
        }
        for o in orgs
    ]

    org_pk_set = {o.pk for o in orgs}
    org_type_by_pk = {o.pk: o.org_type for o in orgs}
    edge_weights = defaultdict(int)

    news_qs = _apply_period_filter(News.objects.all(), start_date, today)
    for news in (
        news_qs
        .prefetch_related("organizations")
        .annotate(org_count=Count("organizations"))
        .filter(org_count__gte=2)
    ):
        pks = sorted(
            o.pk for o in news.organizations.all()
            if o.pk in org_pk_set
        )
        if len(pks) >= 2:
            for a, b in combinations(pks, 2):
                if _edge_allowed(org_type_by_pk[a], org_type_by_pk[b]):
                    edge_weights[(a, b)] += 1

    edges = [
        {"source": str(a), "target": str(b), "value": w}
        for (a, b), w in edge_weights.items()
    ]

    return render(request, "graph/index.html", {
        "nodes": nodes,
        "edges": edges,
        "org_count": len(nodes),
        "edge_count": len(edges),
        "selected_period": period,
    })


def graph_org_panel(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    period = resolve_period(request)
    today = timezone.localtime(timezone.now()).date()
    start_date, today = period_bounds(period, today)

    news_qs = _apply_period_filter(org.news.all(), start_date, today).order_by("-published_at", "-pk")
    total_count = news_qs.count()
    news_list = news_qs.prefetch_related("organizations")[:10]

    return render(request, "graph/_org_panel.html", {
        "org": org,
        "news_list": news_list,
        "total_count": total_count,
        "selected_period": period,
    })


def graph_edge_panel(request, pk_a, pk_b):
    if pk_a == pk_b:
        # 정상 UI 플로우로는 도달 불가(엣지는 항상 서로 다른 두 기업 사이에만 존재) — URL을
        # 직접 편집해 "OrgName × OrgName"처럼 자기 자신과의 엣지를 요청하는 경우를 막는다.
        raise Http404("자기 자신과의 엣지는 존재하지 않습니다.")
    pk_a, pk_b = sorted((pk_a, pk_b))  # 정규화, 2단계 OrgRelation의 org_a.pk < org_b.pk 규칙과 동일
    org_a = get_object_or_404(Organization, pk=pk_a)
    org_b = get_object_or_404(Organization, pk=pk_b)
    period = resolve_period(request)
    today = timezone.localtime(timezone.now()).date()
    start_date, today = period_bounds(period, today)

    # 반드시 두 번 체이닝한 .filter()로 교집합(AND)을 구현한다 — organizations__in=[a, b] 등
    # 단일 필터는 합집합(OR)이 되어 "둘 중 하나만 있어도 걸리는" 오답을 낸다.
    news_qs = (
        News.objects
        .filter(organizations=org_a)
        .filter(organizations=org_b)
    )
    news_qs = _apply_period_filter(news_qs, start_date, today)
    news_list = (
        news_qs
        .prefetch_related("organizations")
        .order_by("-published_at", "-pk")
        .distinct()
        # distinct() 필요: 두 번의 M2M 체이닝 필터가 각각 JOIN을 만들어 중복 행이 생길 수 있음
    )

    return render(request, "graph/_edge_panel.html", {
        "org_a": org_a,
        "org_b": org_b,
        "news_list": news_list,
        "news_count": news_list.count(),
        "selected_period": period,
    })
