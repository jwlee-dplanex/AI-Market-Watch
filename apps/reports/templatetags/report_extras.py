import bleach
import markdown as md
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

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
