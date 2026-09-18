"""월간 결산 보고서 본문 조립 — 섹션별 표 행을 받아 마크다운 하나로 잇는다.

🔴 2026-09-18 신설. 계기는 사용자 물음 *"5단계 월간 보고서는 잘 구현되어 있지?
기존의 7월 금융권 AI 도입 동향 결산 보고서, 8월 ... 처럼 잘 나오는거지?"*였고,
확인해 보니 **아니었다.**

종전 5단계는 주간과 같은 함수를 불러 주간 양식(`### 이슈 제목` + 산문 + `참고: uid`)을
만들었다. 🔴 **monthly RunJob이 0건이라 한 번도 드러난 적이 없었다.** 기존 7·8월
결산은 RA가 손으로 쓴 것이고 두 건의 양식이 글자 하나 다르지 않다 — 9개 고정
카테고리에 마크다운 표, 표 안 `[3](URL)` 출처 번호, 하단 `### 출처` 목록이다.

이 모듈이 맡는 것은 **번호와 URL**이다. LLM은 표 칸과 uid까지만 만들고, 출처 번호를
매기는 일과 URL을 붙이는 일은 코드가 한다. ⚠️ URL을 LLM에게 받아쓰게 하면 지어낸다
(「무조건 팩트 기반」) — 주간의 `참고: uid` 규약이 선 이유와 같다.
"""

import logging

logger = logging.getLogger(__name__)

#: 출처 섹션의 제목. 🔴 7·8월 결산이 쓰는 그대로다 — 다른 섹션과 같은 `###` 높이이고
#: 앞에 번호가 붙지 않는다(9개 카테고리만 번호를 갖는다).
SOURCE_HEADING = "### 출처"


def _table(columns, rows_md) -> str:
    """마크다운 표를 만든다. columns 끝에 「출처」를 붙인다(LLM이 모르는 칸이다)."""
    head = "| " + " | ".join(list(columns) + ["출처"]) + " |"
    rule = "|" + "|".join(["---"] * (len(columns) + 1)) + "|"
    return "\n".join([head, rule] + rows_md)


def build_monthly_content(section_rows, news_by_uid):
    """섹션별 표 행을 본문 마크다운 하나로 잇는다.

    Args:
        section_rows: [(section_dict, rows), ...] 순서대로. rows는
            [{"cells": [...], "news_uids": [...]}, ...]이며
            services/llm.py generate_monthly_section()이 돌려준 모양 그대로다.
        news_by_uid: {uid 문자열: News} — 표에 쓸 수 있는 기사만 담는다.

    Returns:
        (content, used_news, kept_rows) — content는 마크다운 전체, used_news는 실제로
        인용된 News 목록(출처 번호 순), kept_rows는 **표에 실제로 남은 행 수**다.
        🔴 **used_news가 곧 Report.news다** — 주간의 "모든 `참고:` 줄 uid의 합집합 =
        Report.news"와 같은 무결성 규약이다.
        ⚠️ kept_rows를 따로 돌려주는 이유 — 호출부의 빈 보고서 검사가 **LLM이 낸 행
        수가 아니라 살아남은 행 수**를 봐야 한다. 버려진 행까지 세면 표가 거의 비었는데
        검사를 통과한다.

    🔴 버리는 행이 있다. 둘 다 조용히 넘기지 않고 로그를 남긴다.
      - cells 개수가 그 섹션 columns와 다른 행: 표가 깨진다.
      - 근거 uid가 하나도 해결되지 않은 행: 출처 없는 사실이 된다(「무조건 팩트 기반」).
    """
    number_by_uid = {}
    used_news = []
    body = []
    kept_rows = 0
    dropped_shape = dropped_source = 0

    for section, rows in section_rows:
        columns = section["columns"]
        rows_md = []
        for row in rows or []:
            cells = [str(c).replace("|", "/").replace("\n", " ").strip()
                     for c in (row.get("cells") or [])]
            if len(cells) != len(columns):
                dropped_shape += 1
                continue

            # uid를 출처 번호로 바꾼다. 처음 나온 기사가 그 번호를 갖는다 — 표를
            # 위에서 아래로 읽는 순서와 번호 순서가 같아진다.
            marks = []
            for raw in row.get("news_uids") or []:
                uid = str(raw).strip()
                news = news_by_uid.get(uid)
                if news is None:
                    continue
                if uid not in number_by_uid:
                    number_by_uid[uid] = len(used_news) + 1
                    used_news.append(news)
                marks.append("[%d](%s)" % (number_by_uid[uid], news.url))
            if not marks:
                dropped_source += 1
                continue

            rows_md.append("| " + " | ".join(cells + [" ".join(marks)]) + " |")

        if not rows_md:
            # 🔴 재료가 없는 섹션은 통째로 뺀다. 빈 표를 두면 「이번 달에 없었다」가
            # 아니라 「만들다 말았다」로 읽힌다. 7·8월도 9개가 다 채워졌을 뿐
            # 빈 섹션을 둔 전례가 없다.
            continue
        kept_rows += len(rows_md)
        body.append("### %d. %s (%d건)" % (section["no"], section["name"], len(rows_md)))
        body.append("")
        body.append(_table(columns, rows_md))
        body.append("")

    if dropped_shape or dropped_source:
        logger.warning(
            "월간 표 조립: 칸 수가 맞지 않는 행 %d개와 근거를 못 찾은 행 %d개를 뺐어요.",
            dropped_shape, dropped_source,
        )

    if used_news:
        body.append(SOURCE_HEADING)
        body.append("")
        for i, news in enumerate(used_news, 1):
            title = (news.title or "").replace("[", "(").replace("]", ")")
            body.append("%d. [%s](%s)" % (i, title, news.url))

    return "\n".join(body).strip() + "\n", used_news, kept_rows
