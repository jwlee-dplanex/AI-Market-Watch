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

from django.db.models import Max, Min


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

    🔴 기준은 근거 뉴스 발행일의 최댓값 단독이 아니라 "그 Insight가 연결한 News의
    published_at 구간[최솟값, 최댓값]이 대상 기간과 겹치는가"다(구간 겹침, docs/planning.md
    7-1 정본 — "최솟값도 최댓값도 아니고 집합이 겹치는가를 묻는다"). 2026-09-17까지는
    Max만 보는 코드였다 — 최댓값이 기간 안이면 통과, 밖이면 무조건 탈락시켰는데, 이슈
    하나가 여러 날에 걸친 후속 보도를 계속 흡수하면(예: 이번 주에 만들어진 이슈가
    다음 주에도 관련 후속 기사를 새로 받는 경우) 최댓값이 기간 상단 밖으로 밀려나
    "그 기간 뉴스를 갖고 있는데도 빠지는" 결과를 냈다.

    🔴 **실측(2026-09-17, PE)** — 코드와 문서(7-1)가 실제로 갈리는지 이번 라운드
    확정 전에 먼저 쟀다(원칙 "고치기 전에 실측"). 결과는 "9/25부터 갈릴 수 있다"는
    추정보다 심각했다 — **이미 지금 갈리고 있었다.** 다음 4단계(주간) 실행이 실제로
    쓸 이번 대상 주(`target_week()` 산출 2026-09-05~09-11)를 옛 Max 방식과 이 구간
    겹침 방식으로 각각 돌려 비교하니 **21건 대 26건(+5)** — Insight 112·159·165·168·
    182 다섯 건이 옛 방식에서 빠져 있었다(전부 대상 주 안에 근거 뉴스가 있는데, 그
    뒤로도 관련 후속 보도가 계속 나와 최댓값이 9/14까지 밀려난 경우). 과거 실제
    Report 9건(주간 7 + 월간 2, 2026-07-03~2026-09-11 전 구간)에도 전부 같은 방향
    (구간 겹침이 항상 Max 방식의 상위집합, 0건 제거·2~5건씩 추가)으로 나타났다 —
    수학적으로도 그렇다: `date_from<=max<=date_to`(옛 조건)가 참이면
    `min<=max<=date_to`이고 `max>=date_from`이 자동으로 성립해 새 조건을 항상
    함의하므로, 구간 겹침은 절대 옛 결과를 줄이지 않고 늘리기만 한다(회귀 위험 없음).
    ⚠️ 다만 과거 Report 비교는 "그 시점에 존재했던 Insight"가 아니라 "오늘 존재하는
    전체 Insight"로 다시 돌린 것이라, 그 차이에는 이 로직 차이뿐 아니라 그 뒤에 RA가
    새로 만든 Insight가 옛 기간 뉴스를 참조하는 경우도 섞여 있다 — 과거 Report 본문이
    실제로 틀렸다는 뜻은 아니다(재생성한 적이 없어 그 시점 결과가 그대로 남아 있다).
    확실한 것은 "지금 이 함수를 다시 부르면" 이번 주 숫자부터 이미 달라진다는 것이다.

    Insight.created_at은 RA(또는 확정 시점)가 쓴 시각이라 재작성 때 전부 같은 날로
    몰려 기간 판별에 쓸 수 없다 — 대시보드가 이미 같은 이유로 그 정렬을 폐기했다
    (apps/dashboard/views.py latest_news_at 주석). 이 정의를 4·5단계 LLM에 넘기는
    입력 기사 범위와도 일치시킨다.
    """
    from apps.news.models import Insight

    return Insight.objects.annotate(
        earliest_news_at=Min("news__published_at"),
        latest_news_at=Max("news__published_at"),
    ).filter(
        earliest_news_at__date__lte=date_to, latest_news_at__date__gte=date_from,
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
