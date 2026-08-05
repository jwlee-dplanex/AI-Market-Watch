import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from services.text_cleaning import clean_lines, ends_with_terminal_punct

register = template.Library()

# ---------------------------------------------------------------------------
# News.body 스크랩 잔여물 필터 (NEWS-002 본문 표시, 2026-08-05)
#
# 잔여물 제거 자체(이메일/바이라인/저작권/캡션/댓글 UI/관련기사 위젯 등 DROP·
# TRIM 패턴)는 services/text_cleaning.py의 clean_lines()에 있다. 기업/기술
# 주제 태깅(services/collector.py)도 같은 함수를 쓴다 — 화면 렌더링과 태깅
# 대상 텍스트를 만드는 규칙이 어긋나지 않도록 패턴은 그 모듈 하나에만 두고
# 여기서는 가져다 쓰기만 한다. 새 잔여물 패턴이 필요하면 이 파일이 아니라
# services/text_cleaning.py를 고친다.
#
# 이 파일이 맡는 건 화면 전용 관심사뿐이다 — HTML escape, <p> 문단 분리,
# 그리고 아래 소제목(subtitle) 판정.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 소제목(subtitle) 판정 규칙 (NEWS-002 본문 표시, 2026-08-05)
#
# News.body는 소제목도 본문 문단과 구분 없이 같은 한 줄로 저장돼 있어(줄바꿈
# 하나) 문단 여백만으로는 "어디서 화제가 바뀌는지"가 보이지 않는다. 잔여물
# 필터를 통과한 뒤 남은 줄에 실측(검증 뉴스 103건)으로 뽑은 두 규칙을 적용해
# 소제목을 가려낸다.
#
# 원칙은 위 잔여물 필터와 같다 — "의심스러우면 본문으로 둔다". 소제목을
# 놓쳐서 평범한 문단으로 남는 것은 지금과 다를 게 없지만, 본문 문장이
# 소제목으로 잘못 커지면 화면에서 바로 눈에 띈다. 그래서 아래 두 규칙 모두
# "확실한 경우만" 잡도록 좁혔다.
#
#   (1) MARKER  — 줄 맨 앞에 ◆/■/◼/□ 같은 시각적 구분 기호가 붙은 경우.
#                 언론사가 브리핑형 기사(◆ 항목1 ◆ 항목2 ...)에서 즐겨 쓰는
#                 형식이라 신뢰도가 가장 높다. 위치와 무관하게 항상 소제목으로
#                 본다.
#   (2) GENERIC — 마커 없이 짧고(45자 이하) 말줄임표(…)나 쉼표를 포함하면서
#                 문장 종결(. ! ? 또는 ~다/~요로 끝남)이 아닌 줄. 단, 기사
#                 맨 앞에 "진짜 본문 문장"이 한 번도 나오지 않은 구간(부제
#                 묶음 deck)에서는 적용하지 않는다.
# ---------------------------------------------------------------------------

# (1) 마커. ▲/▶는 일부러 뺐다 — 실측 결과 ▲는 인사발령 기사에서 "▲부서명
# 이름" 형태로 한 줄에 여러 번 반복되는 목록에 압도적으로 많이 쓰여(pk=715,
# 한 줄에 ▲가 10개 넘게 반복) 마커로 넣으면 그 기사 전체가 소제목으로
# 도배된다. ▶는 이미 _PROMO_PATTERNS로 걸러지는 홍보 CTA(카카오톡 제보 안내
# 등)에서만 관측됐다.
# ◇는 오히려 반대 사례다 — pk=715 안에서도 ▲이름 목록을 "◇ 부행장 승진"
# "◇ 부행장 전보"처럼 상위 구간으로 묶는 용도로 쓰여(한 줄에 하나씩만 등장),
# 마커로 추가하면 그 인사발령 기사 안에서 승진/전보 구간이 갈라져 오히려
# 가독성이 좋아진다.
_SUBTITLE_MARKER_RE = re.compile(r"^([◆◇■◼□])︎?\s*")

# (2) 문장 종결 판정. "필요"처럼 종결어미가 아닌데 우연히 다/요로 끝나는
# 단어도 있지만(예: pk=1279의 "편리해진 주문, 충동매매로 이어지지 않도록 통제
# 필요"), 이 경우 "종결로 판정 → 소제목 아님(본문 취급)"으로 안전한 방향으로
# 넘어가므로 그대로 둔다. 판정 함수 자체(ends_with_terminal_punct)는
# services/text_cleaning.py에 있다 — 트레일링 하이픈 위젯 탐지(같은 파일의
# _find_trailing_bullet_cutoff)도 "본문이 시작됐는가"를 가르는 데 동일한
# 판정을 쓰므로 기준이 어긋나지 않게 한 곳에만 둔다.
_SUBTITLE_MAX_LEN = 45


def _is_generic_subtitle_candidate(s):
    """마커 없는 줄이 GENERIC 규칙(길이+말줄임표 또는 쉼표+비종결)에 맞는지 본다.

    쉼표를 요구하는 이유: 한국 기사 소제목은 "<주체>, <서술>"처럼 쉼표로
    주체와 내용을 나누는 관행이 뚜렷하다(예: "카카오뱅크, 제휴 금융사와
    함께 우대금리 제공"). 인사발령 기사의 "▲부서명 이름" 목록(pk=715)은
    쉼표가 없어 이 조건만으로 자연히 제외된다.

    "-"로 시작하는 줄은 제외한다: pk=751에서 실측한 결과, 기사 맨 끝에
    "- 카카오페이증권, ..." 식으로 이어지는 하이픈 목록은 이 기사와 무관한
    다른 헤드라인을 나열한 "관련기사" 위젯이었다(내용 문단 없이 헤드라인만
    연속). 이걸 소제목으로 키우면 이 기사 내부의 절 구분처럼 보여 오해를
    준다. 하이픈 목록이 이 기사 자체의 화제 전환인 경우도 있을 수 있지만
    구분할 신호가 없어, 의심스러우면 본문으로 두는 원칙에 따라 일괄 제외한다.
    """
    if s.startswith(("-", "–", "—")):
        return False
    if len(s) > _SUBTITLE_MAX_LEN:
        return False
    if ends_with_terminal_punct(s):
        return False
    return "…" in s or ".." in s or "," in s


def _classify_paragraphs(paragraphs):
    """문단 리스트를 (표시할 텍스트, 소제목 여부) 튜플 리스트로 바꾼다.

    body_started: 기사 맨 앞 "부제 묶음(deck)" 구간을 지났는지 여부. 부제
    묶음(예: pk=1173, 1149)은 제목을 보조하는 짧은 문구가 기사 맨 앞에 여러
    줄 연속으로 붙는 형태로, 화제 전환을 나타내는 소제목과 성격이 다르다
    (섹션을 나누는 게 아니라 제목 보강). 마커 없이는 이 둘을 문자 패턴만으로
    구분할 수 없어, "문장 종결로 끝나는 문단을 한 번이라도 만났는가"로
    위치를 가른다 — 그 전까지는 GENERIC 규칙을 적용하지 않고 그대로 본문
    문단으로 렌더링한다. MARKER 규칙은 위치와 무관하게 항상 적용한다
    (실측 결과 deck에 마커가 붙은 사례는 없었다).
    """
    body_started = False
    result = []
    for p in paragraphs:
        m = _SUBTITLE_MARKER_RE.match(p)
        if m:
            result.append((p[m.end():].strip(), True))
            continue
        if body_started and _is_generic_subtitle_candidate(p):
            result.append((p, True))
            continue
        result.append((p, False))
        if ends_with_terminal_punct(p):
            body_started = True
    return result


@register.filter(name="news_body")
def news_body_filter(text):
    """News.body 원문을 스크랩 잔여물 제거 + 줄 단위 문단 분리 + 소제목 판정해
    안전한 HTML로 바꾼다.

    - News.body는 문단이 줄바꿈 하나(\\n)로 구분돼 있어(검증 뉴스 103건 중
      87건이 단일 개행만, 빈 줄 없음) 표준 `linebreaks` 필터(빈 줄 기준으로
      <p> 생성)를 쓰면 본문 전체가 <p> 하나가 된다. 여기서는 "줄 하나 =
      문단 하나"로 렌더링한다. 빈 줄이 있는 경우도 같은 처리로 자연히
      흡수된다(빈 줄은 버려짐).
    - 소제목으로 판정된 문단은 `news-subtitle` 클래스를 붙여 렌더링한다.
      시각 표현(크기·굵기·여백)은 templates/news/detail.html의 CSS가 맡는다.
    - XSS 방지: 각 줄은 escape()를 거친 뒤 <p> 태그로만 감싼다(마크다운이
      아니라 평문이므로 이스케이프만으로 충분, apps/reports/templatetags의
      markdown 필터와 달리 bleach는 불필요). 마커 문자를 잘라내는 처리는
      escape 이전에 순수 문자열 슬라이싱으로만 이뤄진다.
    """
    if not text:
        return ""

    paragraphs = clean_lines(text)

    parts = []
    for para_text, is_subtitle in _classify_paragraphs(paragraphs):
        cls = ' class="news-subtitle"' if is_subtitle else ""
        parts.append(f"<p{cls}>{escape(para_text)}</p>")
    return mark_safe("".join(parts))
