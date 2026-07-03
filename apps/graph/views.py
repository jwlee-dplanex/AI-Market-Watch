from itertools import combinations
from collections import defaultdict

from django.shortcuts import render, get_object_or_404
from django.db.models import Count

from apps.setting.models import Organization
from apps.news.models import News

CATEGORY_INDEX = {"금융사": 0, "보험사": 1, "AI": 2}


def graph(request):
    orgs = list(
        Organization.objects.filter(is_active=True)
        .annotate(news_count=Count("news"))
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
    edge_weights = defaultdict(int)

    for news in (
        News.objects
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
    })


def graph_org_panel(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    news_list = org.news.prefetch_related("organizations").order_by("-published_at")[:10]
    return render(request, "graph/_org_panel.html", {
        "org": org,
        "news_list": news_list,
    })
