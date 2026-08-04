import re
import uuid

import bleach
import markdown as md
from django import template
from django.utils.safestring import mark_safe

from apps.news.models import News

register = template.Library()

# 줄 시작의 "### 제목" (h3)만 이슈 구분자로 취급한다.
# "^###[ \t]+" 뒤에 '#'이 더 오면(즉 "#### ..."처럼 h4 이상이면) 매치하지 않도록
# 부정형 전방탐색(negative lookahead)을 둔다. re.MULTILINE으로 각 줄의 시작(^)을 인식한다.
_ISSUE_HEADER_RE = re.compile(r"^###[ \t]+(?!#)(.*)$", re.MULTILINE)

# 이슈 블록 최하단 "참고: <uid>, <uid>" 규약 줄. "참고"와 콜론 사이 공백,
# 전각 콜론(：)까지 관용적으로 허용한다(옵션 C 규약, docs/planning.md 참고).
_REF_LINE_RE = re.compile(r"^[ \t]*참고[ \t]*[:：][ \t]*(.*)$")

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


#: RA가 쓰는 보고서 제목은 "2026년 7월 5주차(7.25~7.31) — 실제 제목" 형태다.
#: 화면 헤더에는 기간이 이미 별도 줄로 나오므로 앞부분이 중복이라 떼어내고,
#: 그 앞부분은 PDF 파일명에 쓴다(같은 파싱을 두 군데서 재사용).
#: em dash(—) 외에 en dash(–)·하이픈(-)도 받아주되, 하이픈은 제목 본문에도 흔히
#: 쓰이므로 "앞부분에 '주차' 또는 '월'이 있을 때"만 구분자로 인정한다.
_TITLE_SEPARATORS = ("—", "–", "-")


def _split_report_title(title):
    """보고서 제목을 (기간 표기, 본 제목)으로 나눈다.

    형식을 지키지 않은 제목이면 ("", 원본 전체)를 돌려준다 — 화면에서 제목이 통째로
    사라지는 사고를 막기 위한 방어다. RA가 형식을 바꾸거나 과거 데이터가 다를 수 있다.
    """
    if not title:
        return "", ""
    for sep in _TITLE_SEPARATORS:
        head, found, tail = title.partition(sep)
        if not found or not tail.strip():
            continue
        head = head.strip()
        # 앞부분이 기간 표기처럼 보일 때만 분리한다(하이픈 오분리 방지).
        if "주차" in head or "월" in head:
            return head, tail.strip()
    return "", title.strip()


@register.filter(name="report_title_body")
def report_title_body(title):
    """헤더에 보여줄 본 제목(기간 표기 제외)."""
    return _split_report_title(title)[1]


@register.filter(name="report_title_period")
def report_title_period(title):
    """PDF 파일명에 쓸 기간 표기. 'YYYY년 M월 N주차(...)' → 'M월 N주차'로 줄인다.

    파일명은 짧을수록 낫고, 연도는 파일 목록에서 대개 다른 파일과 함께 보여 맥락이 있다.
    형식이 다르면 원본을 그대로 쓴다.
    """
    head = _split_report_title(title)[0]
    if not head:
        return ""
    head = head.split("(")[0].strip()          # 괄호 안 날짜 범위 제거
    head = re.sub(r"^\d{4}\s*년\s*", "", head)  # 앞의 연도 제거
    return head.strip()


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


def _split_ref_line(body):
    """이슈 블록 body 최하단의 "참고: <uid>, <uid>" 규약 줄을 분리한다.

    옵션 C 규약(docs/planning.md "이슈별 참고뉴스 인라인 규약")에 따라, 마커는
    (참고 규약 줄을 제외한) 블록의 실제 마지막 줄에만 있어야 인정한다 — 그래야
    "블록 마지막 문단 = 시사점" 위치 규칙이 마커 줄 제거 후에도 그대로 성립한다.

    Returns (body_without_ref_line, uid_token_list). 마커 줄이 없으면
    (body, [])를 반환한다 — 옵션 C 이전 과거 데이터의 정상 폴백 경로.
    """
    lines = body.split("\n")

    # 끝에서부터 공백만 있는 줄은 건너뛰고 실제 내용이 있는 마지막 줄을 찾는다.
    last_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip():
            last_idx = i
            break
    if last_idx is None:
        return body, []

    m = _REF_LINE_RE.match(lines[last_idx].strip())
    if not m:
        return body, []

    tokens = [t.strip() for t in m.group(1).split(",")]
    tokens = [t for t in tokens if t]  # 후행 콤마·빈 토큰 관용 처리

    remaining = "\n".join(lines[:last_idx]).strip("\n")
    return remaining, tokens


def _resolve_ref_news(tokens):
    """uid 토큰 목록을 News 조회 결과로 해결한다.

    오타·존재하지 않는 uid·형식 오류 토큰은 예외를 던지지 않고 조용히
    건너뛴다(옵션 C 폴백 규약). 해결된 News는 uid 토큰이 적힌 순서를 보존한다.
    """
    ordered_uuids = []
    for token in tokens:
        try:
            ordered_uuids.append(uuid.UUID(token))
        except (ValueError, AttributeError, TypeError):
            continue  # 미해결 토큰은 스킵, 해결분만 렌더

    if not ordered_uuids:
        return []

    news_by_uid = {n.uid: n for n in News.objects.filter(uid__in=ordered_uuids)}

    resolved = []
    seen = set()
    for u in ordered_uuids:
        if u in seen:
            continue
        seen.add(u)
        news = news_by_uid.get(u)
        if news is not None:
            resolved.append(news)
    return resolved


@register.filter(name="report_issues")
def report_issues(content):
    """Report.content(markdown 원문)를 "### 이슈 제목" 블록 단위로 분할한다.

    RA가 작성하는 보고서 본문은 표준적으로 "### 이슈 제목" (h3)이 반복되는
    구조를 갖는다. REPORT-002 상세 화면에서 이슈별로 개별 카드/섹션을
    렌더링할 수 있도록, 첫 "### " 이전 텍스트(preamble)와 이슈별
    (title, body, news_list) 목록으로 나눠 dict로 반환한다.

    - body는 각 블록 최하단의 "참고: <uid>, ..." 규약 줄(옵션 C, 2026-07-31)을
      떼어낸 뒤의 markdown 원문이며, 필터를 한 번 더 거치지 않는다. 템플릿에서
      기존 |markdown 필터를 그대로 통과시켜 bleach 새니타이즈를 유지해야 한다.
    - news_list는 그 규약 줄의 uid를 조회해 얻은 News 목록(uid 순서 보존)이다.
      규약 줄이 없거나 uid가 하나도 해결되지 않으면 빈 리스트다 — 템플릿은
      `{% if issue.news_list %}`로 감싸 있을 때만 렌더한다.
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
        raw_body = content[body_start:body_end].strip("\n")
        body, ref_tokens = _split_ref_line(raw_body)
        news_list = _resolve_ref_news(ref_tokens)
        issues.append({"title": title, "body": body, "news_list": news_list})

    return {"preamble": preamble, "issues": issues}
