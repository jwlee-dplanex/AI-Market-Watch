import re

import bleach
import markdown as md
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

# 줄 시작의 "### 제목" (h3)만 이슈 구분자로 취급한다.
# "^###[ \t]+" 뒤에 '#'이 더 오면(즉 "#### ..."처럼 h4 이상이면) 매치하지 않도록
# 부정형 전방탐색(negative lookahead)을 둔다. re.MULTILINE으로 각 줄의 시작(^)을 인식한다.
_ISSUE_HEADER_RE = re.compile(r"^###[ \t]+(?!#)(.*)$", re.MULTILINE)

# RA가 Report.content/overview에 넣는 마크다운을 HTML로 렌더링할 때 허용할 태그/속성.
# report.content는 RA(사람)가 작성하지만 XSS 벡터를 원천 차단하기 위해 화이트리스트 방식으로 제한한다.
ALLOWED_TAGS = [
    "p", "br",
    "strong", "em",
    "ul", "ol", "li",
    "a",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "code", "pre", "hr",
]
ALLOWED_ATTRS = {
    "a": ["href", "title"],
}
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


@register.filter(name="markdown")
def markdown_filter(text):
    """마크다운 텍스트를 안전한 HTML로 변환한다.

    - python-markdown은 문단 내부의 단일 줄바꿈을 소프트 브레이크(공백)로 처리해
      RA가 40~45자마다 넣은 수동 줄바꿈이 문단 단위로 재조합된다.
    - bleach.clean으로 허용 태그/속성/URL 프로토콜만 남기고 나머지(script, on* 이벤트
      핸들러, javascript: 스킴 등)는 모두 제거한다.
    """
    if not text:
        return ""

    html = md.markdown(text, extensions=["sane_lists"])
    cleaned = bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    return mark_safe(cleaned)


@register.filter(name="report_issues")
def report_issues(content):
    """Report.content(markdown 원문)를 "### 이슈 제목" 블록 단위로 분할한다.

    RA가 작성하는 보고서 본문은 표준적으로 "### 이슈 제목" (h3)이 반복되는
    구조를 갖는다. REPORT-002 상세 화면에서 이슈별로 개별 카드/섹션을
    렌더링할 수 있도록, 첫 "### " 이전 텍스트(preamble)와 이슈별
    (title, body) 목록으로 나눠 dict로 반환한다.

    - body는 markdown 원문 그대로이며, 필터를 한 번 더 거치지 않는다.
      템플릿에서 기존 |markdown 필터를 그대로 통과시켜 bleach 새니타이즈를 유지해야 한다.
    - "### "가 전혀 없는 비표준/과거 데이터는 issues=[]로 반환해 템플릿이
      기존처럼 content 전체를 통짜로 렌더링하도록 폴백시킨다.
    """
    if not content:
        return {"preamble": "", "issues": []}

    matches = list(_ISSUE_HEADER_RE.finditer(content))
    if not matches:
        return {"preamble": content, "issues": []}

    preamble = content[: matches[0].start()]

    issues = []
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[body_start:body_end].strip("\n")
        issues.append({"title": title, "body": body})

    return {"preamble": preamble, "issues": issues}
