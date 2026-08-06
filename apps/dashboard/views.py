from datetime import timedelta

from django.db.models import Count, F, Max, Min, Q
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from apps.news.models import Insight, News
from apps.setting.models import Organization, TechTopic
from services.periods import period_bounds, resolve_period

PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 16, 6, 8, 18
VIEW_W = 300
VIEW_H = 100
CHART_W = VIEW_W - PAD_LEFT - PAD_RIGHT
CHART_H = VIEW_H - PAD_TOP - PAD_BOTTOM
BASELINE_Y = PAD_TOP + CHART_H

# "전체" 기간의 버킷 단위 임계값: 주 단위로 그렸을 때 카드 폭이 감당 가능한 최대 포인트 수 기준(PD 결정,
# docs/design.md ALL-001 "기간 필터 + 뉴스 건수 추이 차트 가변화" 절 3번). PE가 임의로 바꾸지 않는다.
WEEK_BUCKET_MAX_DAYS = 364
# 트렌드 차트 dot 개수가 이 값을 넘으면 겹침 방지를 위해 dot을 한 단계 작게 그린다(PD 결정, 임계값 그대로 유지).
DOT_DENSE_THRESHOLD = 15


def _pct(value, max_value):
    """max_value가 0이면 0을 반환(0으로 나누기 방어)."""
    if not max_value:
        return 0
    return round(value / max_value * 100)


def _daily_counts_map(start_date, today):
    """News.published_at 기준 일별 건수 맵을 단일 쿼리로 구한다.
    start_date가 None이면 "전체" 기간 — 하한·상한 어느 쪽도 걸지 않고 전량을 집계한다
    (그래프 앱의 _apply_period_filter와 동일한 "전체=필터 없음" 계약, services/periods.py 참고)."""
    current_tz = timezone.get_current_timezone()
    # 검증 게이트(docs/planning.md): 핵심 지표는 직접 조회 경로이므로 검증분만 집계한다.
    qs = News.objects.verified()
    if start_date is not None:
        qs = qs.filter(published_at__date__gte=start_date, published_at__date__lte=today)
    rows = (
        qs
        .annotate(day=TruncDate("published_at", tzinfo=current_tz))
        .values("day")
        .annotate(count=Count("pk"))
    )
    return {row["day"]: row["count"] for row in rows}


def _build_trend_line_path(points):
    """"수평 탄젠트" 3차 베지어를 N개 포인트로 일반화(docs/design.md 5번 절 참고)."""
    if not points:
        return ""
    d = f"M {points[0]['x']},{points[0]['y']}"
    for i in range(1, len(points)):
        x0, y0 = points[i - 1]["x"], points[i - 1]["y"]
        x1, y1 = points[i]["x"], points[i]["y"]
        cx = (x0 + x1) / 2
        d += f" C {cx},{y0} {cx},{y1} {x1},{y1}"
    return d


def _build_trend_area_path(points, line_path, baseline_y=BASELINE_Y):
    if not points:
        return ""
    first_x, last_x = points[0]["x"], points[-1]["x"]
    return f"{line_path} L {last_x},{baseline_y} L {first_x},{baseline_y} Z"


def _build_day_buckets(today, start_date):
    """"7d"/"30d" 전용 — 일 단위 버킷. start_date부터 오늘까지 하루씩.
    버킷 개수는 (today - start_date).days + 1로 유도한다 — 호출부(dashboard())가 이미
    period_bounds()로 start_date를 결정했으므로 여기서 "7d"/"30d" 문자열로 다시
    판단하지 않는다(중복 계산 제거)."""
    days = (today - start_date).days + 1
    buckets = []
    for i in range(days):
        day = start_date + timedelta(days=i)
        buckets.append({"start": day, "end": day})
    return buckets


def _build_rolling_buckets(today, earliest_date, bucket_size):
    """"전체" 기간용 — 오늘부터 거꾸로 굴리는 롤링 윈도우 버킷(캘린더 주/월 경계가 아님).
    docs/design.md "기간 필터 + 뉴스 건수 추이 차트 가변화" 3번 절의 알고리즘을 그대로 구현."""
    buckets = []
    i = 0
    while True:
        end = today - timedelta(days=i * bucket_size)
        start = end - timedelta(days=bucket_size - 1)
        buckets.append({"start": start, "end": end})
        if end < earliest_date:
            break
        i += 1
    buckets.reverse()
    return buckets


def _build_trend_points(start_date, today, bucket_unit, earliest_date):
    """가변 버킷(일/주/월) 대응 뉴스 건수 추이 포인트를 계산한다.
    반환값: (trend_points, trend_max_count)."""
    counts_by_date = _daily_counts_map(start_date, today)

    if bucket_unit == "day":
        buckets = _build_day_buckets(today, start_date)
    else:
        bucket_size = 7 if bucket_unit == "week" else 30
        buckets = _build_rolling_buckets(today, earliest_date, bucket_size)

    for bucket in buckets:
        span = (bucket["end"] - bucket["start"]).days + 1
        bucket["count"] = sum(
            counts_by_date.get(bucket["start"] + timedelta(days=d), 0)
            for d in range(span)
        )

    n = len(buckets)
    max_count = max((b["count"] for b in buckets), default=0)
    interval = max(1, round(n / 6)) if n else 1

    trend_points = []
    for i, bucket in enumerate(buckets):
        pct = _pct(bucket["count"], max_count)
        label = bucket["start"].strftime("%m/%d")
        if bucket_unit == "day":
            range_label = label
        else:
            range_label = f"{bucket['start'].strftime('%m/%d')}~{bucket['end'].strftime('%m/%d')}"

        if n > 1:
            x = round(PAD_LEFT + i * (CHART_W / (n - 1)))
        else:
            x = round(PAD_LEFT + CHART_W / 2)
        y = round(PAD_TOP + CHART_H - (pct / 100 * CHART_H))

        trend_points.append({
            "label": label,
            "range_label": range_label,
            "count": bucket["count"],
            "pct": pct,
            "is_current": i == n - 1,
            "x": x,
            "y": y,
            "show_label": (i % interval == 0) or (i == n - 1),
        })

    return trend_points, max_count


def _date_filter(field_prefix, start_date, today):
    """start_date가 None(전체 기간)이면 빈 Q()(필터 없음)를 반환한다 — 그래프 앱의
    _apply_period_filter와 동일한 "전체=필터 없음" 계약(services/periods.py 참고).
    field_prefix는 "news__published_at" 또는 "published_at"처럼 필드 경로."""
    if start_date is None:
        return Q()
    return Q(**{
        f"{field_prefix}__date__gte": start_date,
        f"{field_prefix}__date__lte": today,
    })


def _build_org_ranking(start_date, today):
    # 검증 게이트: 기업별 건수 Top 10은 ALL-001 핵심 지표 3종 중 하나(직접 조회 경로)이므로
    # 검증분만 센다. Count(filter=...)는 annotate 앞에서 JOIN 자체를 거르지 않으므로
    # 별도 Q(news__status=...)를 date_filter에 AND로 얹는다.
    date_filter = _date_filter("news__published_at", start_date, today) & Q(news__status=News.STATUS_VERIFIED)
    news_filter = _date_filter("published_at", start_date, today)
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
            .verified()
            .filter(news_filter)
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
    # 검증 게이트: 기술 주제별 언급 건수도 ALL-001 핵심 지표 3종 중 하나(직접 조회 경로).
    date_filter = _date_filter("news__published_at", start_date, today) & Q(news__status=News.STATUS_VERIFIED)
    news_filter = _date_filter("published_at", start_date, today)
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
            .verified()
            .filter(news_filter)
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


def _build_metrics_context(request):
    """"핵심 지표" 섹션(추이 차트 + 기업별/기술주제별 랭킹) 컨텍스트를 만든다.

    전체 페이지 뷰(dashboard)와 HTMX 부분 갱신 뷰(dashboard_metrics)가 이 함수를
    공유한다 — 기간 필터 버튼을 눌렀을 때 핵심 지표 3카드만 갈아끼우기 위해
    fragment 전용 경로를 새로 만들면서, 집계 로직이 두 뷰로 복붙되어 갈라지지
    않도록 여기 한 곳으로 모았다(2026-08-06, PE, 사용자 요청).
    """
    period = resolve_period(request)
    today = timezone.localtime(timezone.now()).date()
    start_date, _ = period_bounds(period, today)

    earliest_date = None
    if period == "all":
        # 검증 게이트: 트렌드 차트 범위도 핵심 지표 소속이므로 검증분 기준으로 잡는다.
        earliest = News.objects.verified().aggregate(Min("published_at"))["published_at__min"]
        earliest_date = timezone.localtime(earliest).date() if earliest else today
        total_days = (today - earliest_date).days + 1
        bucket_unit = "week" if total_days <= WEEK_BUCKET_MAX_DAYS else "month"
    else:
        bucket_unit = "day"

    trend_points, trend_max_count = _build_trend_points(
        start_date, today, bucket_unit, earliest_date
    )
    has_trend_data = trend_max_count > 0
    trend_line_path = _build_trend_line_path(trend_points)
    trend_area_path = _build_trend_area_path(trend_points, trend_line_path)
    # 점(dot) 개수가 많아질수록(최근 30일=30개) 호버 히트박스가 겹치지 않도록 크기를 줄인다.
    # 임계값(DOT_DENSE_THRESHOLD=15)은 그대로 유지하되, 판단은 템플릿이 아니라 여기서 한다
    # (docs/design.md "SVG 좌표는 뷰에서 계산" 원칙을 점 크기 플래그까지 확장 — 코드리뷰 지적).
    trend_dense = len(trend_points) > DOT_DENSE_THRESHOLD

    org_ranking = _build_org_ranking(start_date, today)
    tech_topic_counts = _build_tech_topic_counts(start_date, today)

    return {
        "period": period,
        "bucket_unit": bucket_unit,
        "trend_points": trend_points,
        "trend_max_count": trend_max_count,
        "has_trend_data": has_trend_data,
        "trend_line_path": trend_line_path,
        "trend_area_path": trend_area_path,
        "trend_dense": trend_dense,
        "org_ranking": org_ranking,
        "tech_topic_counts": tech_topic_counts,
    }


def dashboard(request):
    context = _build_metrics_context(request)

    # "RA가 Insight를 만든 시각"이 아니라 "근거 기사가 실제로 최신인가"를 기준으로 정렬한다
    # (사용자 확정 요구사항) — latest_news_at은 근거 뉴스(M2M)의 published_at 중 최댓값.
    # 근거 뉴스가 0건이면 NULL이 되는데, PostgreSQL은 기본적으로 내림차순에서 NULL을 앞에
    # 놓으므로 nulls_last=True로 뒤로 보낸다. 동률(tie) 대비 -pk를 tie-breaker로 포함
    # (검증된 구현 패턴 5번).
    insights = (
        Insight.objects
        .annotate(news_count=Count("news"), latest_news_at=Max("news__published_at"))
        .prefetch_related("news")
        .order_by(F("latest_news_at").desc(nulls_last=True), "-pk")[:20]
    )
    # 최신 뉴스는 기간 필터와 무관하게 항상 전체에서 최신 10건을 보여준다. 기간 셀렉터
    # (7d/30d/전체)는 "핵심 지표" 섹션 전용이며, 주요 이슈·최신 뉴스는 기간과 별개로 항상
    # 현재 기준을 노출한다(사용자 확정 2026-07-31 — 기간 = 핵심 지표 전용).
    latest_news = News.objects.verified().order_by("-published_at")[:30]

    context["insights"] = insights
    context["latest_news"] = latest_news
    return render(request, "dashboard/index.html", context)


def dashboard_metrics(request):
    """핵심 지표 3카드만 렌더링하는 HTMX 부분 갱신 경로(fragment).

    기간 필터 버튼(hx-get)이 이 뷰를 호출해 #dashboard-metrics를 outerHTML로
    교체한다 — 전체 페이지가 다시 로드되지 않으므로 <main>의 스크롤 위치가
    그대로 유지된다. 집계 로직은 dashboard()와 _build_metrics_context()를
    공유한다(위 함수 docstring 참고).
    """
    context = _build_metrics_context(request)
    return render(request, "dashboard/_metrics.html", context)
