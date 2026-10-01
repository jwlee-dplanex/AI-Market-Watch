"""보고서 초안의 낱말이 근거 기사 원문에 실제로 있는지 대조한다.

🔴 2026-09-18 신설. 사용자 지시: *"무조건 팩트 기반이어야한다는게 가장 중요해
주간 보고서는 항상 다 작성하면 팩트 기반인 지 더블체크해야하고"*.

계기 — 9월 3주차 보고서(Report 25)의 개요에 **「신용심사와 보험 인수심사 자동화율이
90%대에 도달했으며」**가 실렸다. 근거 기사 8건을 손으로 대조하니 🔴 **「신용심사」와
「신용평가」가 8건 전부에 없었고**, 실제 값은 95%(KDB생명)와 40%(현대해상)였다.
40%를 90%대에 넣은 것이다. 본문 수치 6개와 영문 16개는 전부 근거에 있었다.

⚠️ **개요가 구멍인 이유는 구조적이다.** 본문 이슈 블록은 `참고: <uid>` 줄로 근거가
박혀 있어 그 기사만 상대로 대조할 수 있지만, **개요에는 그 장치가 없다.** 그래서
개요는 그 보고서의 근거 기사 **전체**를 상대로 본다.

🔴 **이 모듈은 판정하지 않는다. 「기사에서 못 찾았다」까지만 말한다.** 표현이 달라서
못 찾는 경우(「7만장」과 「7만 장」, 「40% 이상」과 「40%」)가 있어 기계가 최종 판단을
하면 안 된다 — 확정을 막지 않고 검토 화면에 보여 주는 것이 사용자 확정 사항이다.

⚠️ 무엇을 못 잡는지 분명히 해 둔다. 한글은 형태소 분석기가 없어 **네 글자 이상
덩어리의 접두사 대조**로만 본다. 두세 글자 낱말과, 기사에 없는 말로 바꿔 쓴 총평
문장은 잡히지 않는다. **이 대조를 통과한 것이 팩트라는 뜻이 아니다.**
"""

import logging
import re

logger = logging.getLogger(__name__)

#: 수치 표현 — 🔴 **비율과 큰 값, 시간, 금액만** 본다(2026-09-18 실측으로 좁혔다).
#:
#: 처음에는 개수(곳·개·건·명·종)와 연도(년)까지 넣었다가 세 보고서로 재 보고 뺐다.
#: 그 종류에서 나온 「못 찾음」 네 개(`5곳`·`11곳`·`10개사`·`2026년`)가 **전부 표현
#: 차이로 인한 오탐**이었고, 진짜로 걸린 하나는 🔴 `90%`(9월 3주차 개요)였다.
#: ⚠️ 좁혀도 놓치는 것이 없음을 확인했다 — 3주차 본문 수치 여섯 개(95%·40%·7만장·
#: 5초·6종 등) 가운데 이 패턴에 걸리는 것은 전부 근거에서 찾혔다.
_NUMBER_RE = re.compile(
    r"\d[\d,\.]*\s*(?:%p|%P|%|퍼센트|만\s*장|만|억|조|달러|원|초|분|시간|배)"
)

#: 영문·약어·제품명. 두 글자 이하는 오탐이 많아 버린다(AI, AX, IT).
#: 🔴 실측에서 **오탐이 0개**였다(세 보고서, 영문 토큰 수십 개). 제품명과 약어는
#: 기사 원문의 표기를 그대로 옮겨 적기 때문이다 — 이 대조가 가장 잘 듣는 자리다.
_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-\.]{2,}")

#: 🔴 한글은 대조하지 않는다(2026-09-18 실측 결론).
#:
#: 네 글자 이상 덩어리의 접두사 대조를 만들어 세 보고서에 돌렸더니 **못 찾음이
#: 131개**였고 「들어오면서」·「때문이다」·「방향이다」처럼 **거의 전부가 용언
#: 활용형 오탐**이었다. 잡아야 할 「신용심사와」는 잡혔지만 오탐 14개에 묻혀 읽을
#: 수 없는 신호가 됐다. ⚠️ **조사와 어미를 떼려면 형태소 분석기가 필요하고 이
#: 프로젝트에 없다.** 오탐이 섞인 경고는 없는 경고보다 나쁘다 — 사람이 곧 무시한다.
#:
#: 그래서 한글 쪽 팩트 확인은 기계가 아니라 **사람이 한다.** 화면이 근거 기사를
#: 이슈마다 함께 보여 주는 것이 그 자리다(run_review.html의 「근거 기사」 접기).

#: 대조에서 빼는 영문. 보고서 전반에 쓰는 일반 약어라 어느 기사에나 있거나 없다.
_LATIN_STOPWORDS = {"AI", "AX", "IT", "OCR", "LLM", "API", "ESG", "CEO", "CIO"}


def _normalize(text: str) -> str:
    """대조용 정규화 — 공백과 쉼표를 없앤다. 「40% 이상」과 「40%이상」을 같게 보고,
    「7만 장」과 「7만장」을 같게 본다."""
    return re.sub(r"[\s,]", "", text or "")


def _haystack(news_list) -> str:
    """근거 기사의 제목과 본문을 정규화해 이어 붙인다."""
    return "\n".join(
        _normalize("%s %s" % (n.title or "", n.body or "")) for n in news_list
    )


def _tokens(text: str) -> list:
    """대조할 낱말을 뽑는다. (종류, 원문 그대로의 낱말) 목록이며 순서와 중복을
    없앤다 — 같은 낱말을 두 번 보고하면 화면이 길어지기만 한다."""
    found, seen = [], set()
    for kind, pattern in (("number", _NUMBER_RE), ("latin", _LATIN_RE)):
        for match in pattern.finditer(text or ""):
            token = match.group(0).strip()
            if not token or token in seen:
                continue
            if kind == "latin" and token.upper() in _LATIN_STOPWORDS:
                continue
            seen.add(token)
            found.append((kind, token))
    return found


def _is_found(token: str, haystack: str) -> bool:
    """그 낱말이 근거에 있는가. 정규화한 뒤 그대로 찾는다 — 공백과 쉼표만 무시하므로
    「7만 장」과 「7만장」, 「40% 이상」과 「40%」가 같게 걸린다."""
    needle = _normalize(token)
    if not needle:
        return True
    return needle in haystack


def check_section(text: str, news_list) -> dict:
    """한 구역(개요 또는 이슈 블록)을 그 구역의 근거 기사와 대조한다.

    Returns:
        {"checked": 전체 낱말 수, "missing": [(종류, 낱말), ...]}
    """
    haystack = _haystack(news_list)
    tokens = _tokens(text)
    if not haystack:
        # 근거 기사가 없으면 대조할 대상 자체가 없다 — 「못 찾음」으로 몰면 낱말
        # 전부가 빨갛게 뜨고 그것은 읽을 수 있는 신호가 아니다. 근거 0건은
        # services/runner.py의 _assert_report_usable()이 이미 실패로 막는다.
        return {"checked": len(tokens), "missing": []}
    missing = [(kind, token) for kind, token in tokens if not _is_found(token, haystack)]
    return {"checked": len(tokens), "missing": missing}


#: 개요를 가리키는 이름. 못 찾은 줄의 「어디」 칸에 그대로 쓴다 — 화면의 이름표가
#: 「주요 동향」이므로 그 말을 쓴다(design.md 1.0.3 이름표는 문어체 명사형).
OVERVIEW_LABEL = "주요 동향"


def check_report(content: str, overview: str, news_list) -> dict:
    """보고서 초안 하나를 통째로 대조한다.

    본문은 이슈마다 **그 이슈의 `참고:` 줄에 적힌 기사**와 대조하고, 개요는 근거
    기사 **전체**와 대조한다(모듈 독스트링 ⚠️ 참고).

    Returns:
        {
          "checked": 검사한 낱말 총수,
          "missing_count": 못 찾은 낱말 총수,
          "rows": [{"where": "주요 동향"|이슈 제목, "token": "90%"}, ...],
        }
        🔴 rows는 템플릿이 그대로 도는 평탄한 목록이다 — 개요와 이슈를 한 목록에
        담는다. 화면이 묶어 보여 줄 이유가 없다(못 찾은 것은 대개 한두 개다).
    """
    from apps.reports.templatetags.report_extras import report_issues

    overview_result = check_section(overview, news_list)
    checked = overview_result["checked"]
    rows = [
        {"where": OVERVIEW_LABEL, "token": token}
        for _kind, token in overview_result["missing"]
    ]

    for issue in report_issues(content or "")["issues"]:
        section = check_section(
            "%s\n%s" % (issue["title"], issue["body"]), issue["news_list"],
        )
        checked += section["checked"]
        rows.extend(
            {"where": issue["title"], "token": token}
            for _kind, token in section["missing"]
        )

    return {"checked": checked, "missing_count": len(rows), "rows": rows}


# ---------------------------------------------------------------------------
# 전 달 결산과의 겹침 — 월간 전용
#
# 🔴 2026-10-01 신설. 사용자 지시: *"8월과 겹치는 내용이 없는 지 확인해줘 이건
# 월간 보고서 만들때 항상 확인해야겠는데?"*.
#
# 「항상」이어서 코드로 옮긴다. 9월 결산을 만들 때 제가 손으로 대조해 겹침 0을
# 확인했는데, 그런 확인은 기억에 맡기면 반드시 빠진다 — 주간에서 본문 수치만 보고
# 개요를 빼먹었던 것과 같은 실패다.
#
# ⚠️ 겹침이 있다고 틀린 것은 아니다. 같은 회사가 달을 걸쳐 후속 소식을 내는 것은
# 정상이므로, 확정을 막지 않고 「겹친다」까지만 말한다(근거 대조와 같은 판단).
# ---------------------------------------------------------------------------


def _table_rows(markdown: str) -> set:
    """표 행을 (첫 칸, 둘째 칸) 쌍 집합으로 뽑는다.

    월간 본문은 섹션마다 컬럼이 다르지만 첫 두 칸이 늘 「누가 · 무엇을」이라
    (기업+적용 대상, 주체+내용) 그 둘로 같은 항목인지 가린다. ⚠️ 헤더 줄은
    첫 칸이 「기업」이나 「주체」라 그것으로 걸러낸다.
    """
    rows = set()
    for line in (markdown or "").split("\n"):
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("기업", "주체"):
            continue
        rows.add((cells[0], cells[1][:24]))
    return rows


def check_previous_month(content: str, news_list, previous_report) -> dict:
    """월간 초안이 전 달 결산과 겹치는지 본다.

    Args:
        content: 이번 초안 본문(마크다운)
        news_list: 이번 초안의 근거 News 목록
        previous_report: 직전 월간 Report (없으면 None)

    Returns:
        {
          "has_previous": bool,          # 비교 대상이 있었는가
          "previous_title": str,
          "news": [News, ...],           # 겹치는 근거 기사
          "rows": [(기업, 항목), ...],    # 겹치는 표 항목
          "row_total": int,              # 이번 초안의 표 행 수(모수)
        }
        🔴 news와 rows가 모두 비면 겹침이 없다는 뜻이다.
    """
    if previous_report is None:
        return {
            "has_previous": False, "previous_title": "",
            "news": [], "rows": [], "row_total": len(_table_rows(content)),
        }

    prev_ids = set(previous_report.news.values_list("pk", flat=True))
    overlap_news = [n for n in news_list if n.pk in prev_ids]

    this_rows = _table_rows(content)
    prev_rows = _table_rows(previous_report.content)
    overlap_rows = sorted(this_rows & prev_rows)

    if overlap_news or overlap_rows:
        logger.warning(
            "월간 초안이 직전 결산(%s)과 겹쳐요 — 근거 기사 %d건, 표 항목 %d개.",
            previous_report.title, len(overlap_news), len(overlap_rows),
        )

    return {
        "has_previous": True,
        "previous_title": previous_report.title,
        "news": overlap_news,
        "rows": overlap_rows,
        "row_total": len(this_rows),
    }
