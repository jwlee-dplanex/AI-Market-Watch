from itertools import combinations
from collections import defaultdict

from django.http import Http404
from django.shortcuts import render, get_object_or_404
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.setting.models import Organization, OrgRelation, normalize_org_pair
from apps.news.models import News
from services.periods import period_bounds, resolve_period

MAX_LABEL_LENGTH = 50  # OrgRelation.label = CharField(max_length=50)과 반드시 일치

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
    org_pk_set = {o.pk for o in orgs}

    # OrgRelation 조회는 유지하되, 용도는 "이미 기간 내에 실존하는 엣지에 라벨 정보를
    # 얹는 것"으로만 쓴다(노드/엣지 강제 부활 없음 — docs/planning.md
    # "지식그래프: 라벨 강제 표시 롤백" 정책, 2026-07-28).
    relations = list(OrgRelation.objects.select_related("org_a", "org_b").all())

    nodes = [
        {
            "id": str(o.pk),
            "name": o.name,
            "category": CATEGORY_INDEX.get(o.org_type, 0),
            "symbolSize": max(14, min(40, 14 + o.news_count * 2)),
        }
        for o in orgs
    ]

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

    # 라벨 정보는 이제 "이미 edge_weights에 실존하는 엣지"에만 얹는다(강제 삽입 없음 —
    # docs/planning.md "지식그래프: 라벨 강제 표시 롤백"). OrgRelation.save()가
    # org_a.pk < org_b.pk로 정규화해 저장하므로 키가 edge_weights의 sorted(a, b) 키와
    # 순서가 항상 일치한다.
    labeled_map = {
        (rel.org_a_id, rel.org_b_id): rel.label
        for rel in relations
        if rel.org_a_id in org_pk_set and rel.org_b_id in org_pk_set
    }

    edges = [
        {
            "source": str(a),
            "target": str(b),
            "value": w,
            "has_label": (a, b) in labeled_map,
            "label": labeled_map.get((a, b)),
        }
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


def _get_edge_orgs_or_404(pk_a, pk_b):
    """엣지 관련 뷰(graph_edge_panel, graph_edge_label_save) 공통 가드 + 정규화.
    자기 자신과의 엣지는 정상 UI 플로우로 도달 불가(엣지는 항상 서로 다른 두 기업 사이에만
    존재) — URL을 직접 편집해 "OrgName × OrgName"을 요청하는 경우만 막는다."""
    if pk_a == pk_b:
        raise Http404("자기 자신과의 엣지는 존재하지 않습니다.")
    pk_a, pk_b = normalize_org_pair(pk_a, pk_b)  # OrgRelation의 org_a.pk < org_b.pk 규칙과 동일
    org_a = get_object_or_404(Organization, pk=pk_a)
    org_b = get_object_or_404(Organization, pk=pk_b)
    return org_a, org_b


def _edge_news_queryset(org_a, org_b, period):
    """org_a·org_b 교집합 뉴스에 선택된 기간(period) 필터를 적용한 쿼리셋.
    graph_edge_panel(화면 표시)과 graph_edge_label_save(근거뉴스 저장)가 이 함수 하나를
    공유한다 — 패널에 실제로 보이는 news_list와 OrgRelation.news로 저장되는 값이 항상
    같은 쿼리에서 나오도록 강제하기 위해서다(docs/planning.md 근거뉴스 범위 확정 정책:
    "패널의 news_list와 저장되는 relation.news는 항상 동일해야 한다", 기간 필터 없는 전체
    교집합을 저장하지 않는다)."""
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
    # distinct() 필요: 두 번의 M2M 체이닝 필터가 각각 JOIN을 만들어 중복 행이 생길 수 있음
    return news_qs.distinct()


def _build_edge_panel_context(org_a, org_b, period):
    """graph_edge_panel과 graph_edge_label_save가 공유하는 쌍 패널 컨텍스트 조립.
    2단계(OrgRelation)에서 저장 후에도 같은 템플릿(_edge_panel.html)을 재렌더링해야 하므로
    두 뷰가 이 헬퍼 하나로 로직을 공유한다(중복 구현 금지 — planning.md 지시)."""
    news_list = (
        _edge_news_queryset(org_a, org_b, period)
        .prefetch_related("organizations")
        .order_by("-published_at", "-pk")
    )

    # 정규화된 (org_a, org_b)로 조회 — 없으면 None. 템플릿은 None을 "관계 미분류"로 표시(PD 설계).
    relation = OrgRelation.objects.filter(org_a=org_a, org_b=org_b).first()

    return {
        "org_a": org_a,
        "org_b": org_b,
        "news_list": news_list,
        "news_count": news_list.count(),
        "selected_period": period,
        "relation": relation,
    }


def graph_edge_panel(request, pk_a, pk_b):
    org_a, org_b = _get_edge_orgs_or_404(pk_a, pk_b)
    period = resolve_period(request)
    context = _build_edge_panel_context(org_a, org_b, period)
    return render(request, "graph/_edge_panel.html", context)


@require_POST
def graph_edge_label_save(request, pk_a, pk_b):
    """2단계 관계 라벨 저장(HTMX POST). RA가 _edge_panel.html의 편집 폼에서 제출한다.
    label은 required(자유 텍스트) — 폼에는 이미 HTML required + maxlength=50이 걸려 있어
    정상 플로우에서는 빈 값이나 50자 초과 값이 오지 않지만, 그건 클라이언트 검증일 뿐이라
    직접 POST(개발자 도구/curl 등)로는 우회 가능하다. 서버단에서도 검증해서, 비어 있거나
    50자(OrgRelation.label의 max_length)를 초과하면 저장하지 않고 현재 상태 그대로 패널을
    재렌더링한다(no-op) — 검증 없이 update_or_create에 그대로 넘기면 50자 초과 시 처리되지
    않은 django.db.utils.DataError로 500이 난다(코드리뷰에서 실제 재현된 버그)."""
    org_a, org_b = _get_edge_orgs_or_404(pk_a, pk_b)
    period = resolve_period(request)

    label = (request.POST.get("label") or "").strip()
    description = (request.POST.get("description") or "").strip()

    if label and len(label) <= MAX_LABEL_LENGTH:
        # 근거뉴스 = _edge_news_queryset(패널이 news_list를 만드는 것과 동일한 쿼리)의
        # 결과 그대로(docs/planning.md 근거뉴스 범위 확정 정책 — 화면에 보이는 선택된 기간의
        # 교집합만 저장, 기간 필터 없는 전체 교집합을 임의로 저장하지 않는다).
        # update_or_create와 news.set()을 하나의 트랜잭션으로 묶어, 라벨은 저장됐는데
        # 근거뉴스 세팅만 실패하는(또는 그 반대) 반쪽 상태가 생기지 않게 한다.
        with transaction.atomic():
            relation, _created = OrgRelation.objects.update_or_create(
                org_a=org_a, org_b=org_b,
                defaults={"label": label, "description": description},
            )
            relation.news.set(_edge_news_queryset(org_a, org_b, period))

    context = _build_edge_panel_context(org_a, org_b, period)
    return render(request, "graph/_edge_panel.html", context)
