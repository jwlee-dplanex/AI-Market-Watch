from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from apps.news.models import Insight, News
from apps.setting.models import Organization, TechTopic

PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 16, 6, 8, 18
VIEW_W = 300
VIEW_H = 100
CHART_W = VIEW_W - PAD_LEFT - PAD_RIGHT
CHART_H = VIEW_H - PAD_TOP - PAD_BOTTOM


def _pct(value, max_value):
    """max_value가 0이면 0을 반환(0으로 나누기 방어)."""
    if not max_value:
        return 0
    return round(value / max_value * 100)


def _build_daily_counts(start_date, today):
    current_tz = timezone.get_current_timezone()
    rows = (
        News.objects
        .filter(published_at__date__gte=start_date, published_at__date__lte=today)
        .annotate(day=TruncDate("published_at", tzinfo=current_tz))
        .values("day")
        .annotate(count=Count("pk"))
    )
    counts_by_date = {row["day"]: row["count"] for row in rows}

    daily_counts = []
    for i in range(7):
        day = start_date + timedelta(days=i)
        daily_counts.append({
            "date": day,
            "label": day.strftime("%m/%d"),
            "count": counts_by_date.get(day, 0),
            "is_today": day == today,
        })

    max_count = max((d["count"] for d in daily_counts), default=0)
    for i, d in enumerate(daily_counts):
        d["pct"] = _pct(d["count"], max_count)
        d["x"] = round(PAD_LEFT + i * (CHART_W / 6))
        d["y"] = round(PAD_TOP + CHART_H - (d["pct"] / 100 * CHART_H))
    return daily_counts, max_count


def _build_org_ranking(start_date, today):
    date_filter = Q(
        news__published_at__date__gte=start_date,
        news__published_at__date__lte=today,
    )
    orgs = list(
        Organization.objects
        .filter(is_active=True)
        .annotate(count=Count("news", filter=date_filter))
        .filter(count__gt=0)
        .order_by("-count", "name")[:10]
    )

    max_count = orgs[0].count if orgs else 0
    org_ranking = []
    for rank, org in enumerate(orgs, start=1):
        recent_news = list(
            org.news
            .filter(published_at__date__gte=start_date, published_at__date__lte=today)
            .order_by("-published_at", "-pk")[:5]
        )
        org_ranking.append({
            "rank": rank,
            "name": org.name,
            "org_type": org.org_type,
            "count": org.count,
            "pct": _pct(org.count, max_count),
            "recent_news": [{"uid": n.uid, "title": n.title} for n in recent_news],
            "more_count": max(org.count - len(recent_news), 0),
        })
    return org_ranking


def _build_tech_topic_counts(start_date, today):
    date_filter = Q(
        news__published_at__date__gte=start_date,
        news__published_at__date__lte=today,
    )
    topics = list(
        TechTopic.objects
        .filter(is_active=True)
        .annotate(count=Count("news", filter=date_filter, distinct=True))
        .filter(count__gt=0)
        .order_by("-count", "name")[:10]
    )

    max_count = topics[0].count if topics else 0
    tech_topic_counts = []
    for rank, topic in enumerate(topics, start=1):
        recent_news = list(
            topic.news
            .filter(published_at__date__gte=start_date, published_at__date__lte=today)
            .order_by("-published_at", "-pk")[:5]
        )
        tech_topic_counts.append({
            "rank": rank,
            "name": topic.name,
            "count": topic.count,
            "pct": _pct(topic.count, max_count),
            "recent_news": [{"uid": n.uid, "title": n.title} for n in recent_news],
            "more_count": max(topic.count - len(recent_news), 0),
        })
    return tech_topic_counts


def dashboard(request):
    insights = (
        Insight.objects
        .annotate(news_count=Count("news"))
        .prefetch_related("news")
        .order_by("-created_at")[:5]
    )
    latest_news = News.objects.order_by("-published_at")[:10]

    today = timezone.localtime(timezone.now()).date()
    start_date = today - timedelta(days=6)

    daily_counts, daily_max_count = _build_daily_counts(start_date, today)
    # daily_counts는 항상 7개 항목을 반환하므로(빈 날짜도 count=0으로 채움) {% if daily_counts %}는
    # 항상 참이 되어 빈 상태 문구가 절대 뜨지 않는다. daily_max_count가 0이면 7일 구간 전체에
    # News가 하나도 없다는 뜻이므로, 이를 별도 플래그로 템플릿에 전달해 표시 여부를 판단한다.
    has_daily_data = daily_max_count > 0
    org_ranking = _build_org_ranking(start_date, today)
    tech_topic_counts = _build_tech_topic_counts(start_date, today)

    return render(request, "dashboard/index.html", {
        "insights": insights,
        "latest_news": latest_news,
        "daily_counts": daily_counts,
        "daily_max_count": daily_max_count,
        "has_daily_data": has_daily_data,
        "org_ranking": org_ranking,
        "tech_topic_counts": tech_topic_counts,
    })
