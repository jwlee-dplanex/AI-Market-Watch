"""SET-010 4~5단계(주간·월간 보고서) 대상 기간 계산 — 단 하나의 정본 함수
(docs/planning.md "3~5단계를 LLM으로 옮기는 설계" 2-1-(d) "버튼 잠금 판정과 보고서
date_from/date_to 저장은 같은 함수 하나가 낸 값을 쓴다. 뷰가 날짜를 따로 계산하지
않는다").

apps/setting/views.py(버튼 잠금, block_reason, summary)와 services/runner.py(_run_report()의
Report 저장)가 이 모듈의 target_week()/target_month()를 함께 쓴다. 두 벌이 되면 잠금이
보는 주와 저장되는 주가 어긋나도 에러가 나지 않는다(같은 문서 경고 — "잠금은 A주를
보고 저장은 B주를 적어도 화면이 아무 말도 하지 않는다").

🔴 insights_in_period()도 같은 이유로 한 벌이다. "대상 기간에 Insight가 0건이다"를
재는 잠금 판정과, 4·5단계 LLM에 넘기는 입력 대상 조회가 다른 쿼리를 쓰면 "이슈가
있다는데 빈 보고서가 나온다"가 된다(같은 절 2-1-(d) 두 번째 문단).
"""
from datetime import timedelta

from django.db.models import Max


def target_week(today):
    """실행 시점 기준 가장 최근 금요일이 속은 토요일부터 금요일까지 구간을 (date, date)로
    반환한다.

    🔴 "실행 시점이 속한 토요일부터"가 아니다 — 그 정의는 토요일에 눌렀을 때 방금
    시작한 새 주를 가리켜, 정작 만들려던 어제 끝난 주가 빠진다(설계 2-1). "가장 최근
    금요일이 속한 주"로 풀면 금요일 당일엔 그날 끝나는(진행 중인) 주를, 토요일부터
    다음 목요일까지는 방금 끝난 주를 가리킨다 — 이 성질이 4단계가 "금요일부터
    열린다"를 별도 요일 검사 없이 성립시킨다.
    """
    # Python의 date.weekday()는 월요일=0 … 금요일=4 … 일요일=6이다.
    days_since_friday = (today.weekday() - 4) % 7
    friday = today - timedelta(days=days_since_friday)
    saturday = friday - timedelta(days=6)
    return saturday, friday


def target_month(today):
    """실행 시점 기준 직전 달 1일부터 말일까지 구간을 (date, date)로 반환한다.

    「결산(월간) 보고서 주기」 확정 규칙 1번 "기간은 달력 월 그대로다 — 1일~말일"을
    그대로 코드로 옮긴 것이다. 대상 월을 직전 달로 고정하므로 "대상 월이 끝났는가"는
    이 함수가 반환하는 구간에 대해 정의상 항상 참이다(설계 2-1-(b) 2번) — 그래서
    5단계에는 "아직 열릴 때가 아니에요"에 해당하는 잠금이 없다.
    """
    first_of_this_month = today.replace(day=1)
    last_of_prev_month = first_of_this_month - timedelta(days=1)
    first_of_prev_month = last_of_prev_month.replace(day=1)
    return first_of_prev_month, last_of_prev_month


def insights_in_period(date_from, date_to):
    """대상 기간(date_from~date_to, 양끝 포함)에 속하는 Insight 쿼리셋.

    기준은 근거 뉴스 발행일의 최댓값(Max("news__published_at"))이다. Insight.created_at은
    RA(또는 확정 시점)가 쓴 시각이라 재작성 때 전부 같은 날로 몰려 기간 판별에 쓸 수
    없다 — 대시보드가 이미 같은 이유로 그 정렬을 폐기했다(apps/dashboard/views.py
    latest_news_at 주석). 대시보드가 쓰는 것과 같은 값이며, 이 정의를 4·5단계 LLM에
    넘기는 입력 기사 범위와도 일치시킨다.
    """
    from apps.news.models import Insight

    return Insight.objects.annotate(latest_news_at=Max("news__published_at")).filter(
        latest_news_at__date__gte=date_from, latest_news_at__date__lte=date_to,
    )


def _week_number_in_month(date_to):
    """date_to(대상 주의 금요일)가 그 달의 몇 번째 금요일인지. 실측(기존 Report
    레코드, 2026-09-15 PE 확인)으로 확인한 규칙이다 — 새로 정하지 않았다."""
    return (date_to.day - 1) // 7 + 1


def weekly_title(date_from, date_to):
    """"YYYY년 M월 N주차(M.D~M.D) — M월 N주차 금융권 AI 도입 동향 보고서" 서식.

    기존 Report 레코드(예: "2026년 9월 1주차(8.29~9.4) — 9월 1주차 금융권 AI 도입
    동향 보고서")에서 그대로 확인한 서식이다 — 「주간 보고서(Report) 표준 구조」
    1번이 이 서식을 고정 서식으로 못박았고, 제목은 LLM이 짓지 않는다(설계 8-(C)).
    N주차는 date_to(금요일)를 기준으로 정한다 — date_from(토요일)이 전달일 수 있어도
    제목의 달은 date_to의 달이다."""
    week_no = _week_number_in_month(date_to)
    date_range = f"{date_from.month}.{date_from.day}~{date_to.month}.{date_to.day}"
    return (
        f"{date_to.year}년 {date_to.month}월 {week_no}주차({date_range}) — "
        f"{date_to.month}월 {week_no}주차 금융권 AI 도입 동향 보고서"
    )


def monthly_title(date_from, date_to):
    """"YYYY년 M월(M.D~M.D) — M월 금융권 AI 도입 동향 결산 보고서" 서식.

    기존 Report 레코드(예: "2026년 8월(8.1~8.31) — 8월 금융권 AI 도입 동향 결산
    보고서")에서 그대로 확인한 서식이다."""
    date_range = f"{date_from.month}.{date_from.day}~{date_to.month}.{date_to.day}"
    return (
        f"{date_to.year}년 {date_to.month}월({date_range}) — "
        f"{date_to.month}월 금융권 AI 도입 동향 결산 보고서"
    )
