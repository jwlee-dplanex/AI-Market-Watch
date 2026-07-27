"""대시보드(ALL-001)·지식그래프(GRAPH-001) 공통 기간 필터 유틸.

두 앱 모두 "전체/최근 30일/최근 7일" 3-옵션 기간 필터를 쓰고, 기준 필드는 항상
News.published_at(발행일, collected_at 아님)이다. 파싱·검증·경계 계산 로직이 앱마다
중복 구현되어 있던 것을 이 모듈로 통합했다(코드리뷰 지적, 2026-07).

"전체"(period="all")는 하한(start_date)뿐 아니라 상한(오늘)도 걸지 않는다 — 즉 필터를
아예 적용하지 않는다. 이는 대시보드·그래프 두 화면이 같은 데이터를 두고 항상 같은
숫자를 보여줘야 한다는 "기간 정합성 계약"을 만족시키기 위함이다(미래 날짜로 잘못
파싱된 published_at이 있어도 두 화면이 동일하게 그 값을 포함/제외해야 함).
"""
from datetime import timedelta

VALID_PERIODS = {"all", "30d", "7d"}


def resolve_period(request):
    """request.GET의 period 값을 검증한다. 없거나 유효하지 않으면 "7d"로 폴백."""
    period = request.GET.get("period", "7d")
    return period if period in VALID_PERIODS else "7d"


def period_bounds(period, today):
    """(start_date, today)를 반환한다.

    - "7d" → (today-6일, today)
    - "30d" → (today-29일, today)
    - "all" → (None, today) — start_date가 None이면 호출부는 하한·상한 어느 쪽도
      걸지 않아야 한다(필터 없음 = "전체"의 정의).

    today는 호출부(각 뷰)가 한 번만 계산해서 넘긴다 — 뷰 안에서 여러 헬퍼가 각자
    timezone.localtime(timezone.now()).date()를 반복 계산하지 않도록 하기 위함.
    """
    if period == "30d":
        return today - timedelta(days=29), today
    if period == "7d":
        return today - timedelta(days=6), today
    return None, today
