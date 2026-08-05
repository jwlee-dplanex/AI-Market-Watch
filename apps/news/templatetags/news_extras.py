import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

# ---------------------------------------------------------------------------
# News.body 스크랩 잔여물 필터 (NEWS-002 본문 표시, 2026-08-05)
#
# 수집기(services/collector.py)가 기사 본문만 깔끔하게 가져오지 못하고 매체
# 사이트의 기자 서명, 저작권 문구, 사진 캡션, 댓글 UI 등 스크랩 잔여물을 함께
# 담아온다. News.body 원문은 절대 고치지 않는다(매체마다 형식이 계속 바뀔
# 텐데, 원문이 남아 있어야 규칙을 고쳤을 때 다시 적용할 수 있다) — 화면에
# 렌더링할 때만 걸러낸다.
#
# 원칙: "의심스러우면 남긴다". 본문이 사라지는 사고가 잔여물이 남는 것보다
# 훨씬 나쁘다. 검증된 뉴스 103건(1,987줄)을 실측해 아래 패턴을 뽑았다.
# 매체가 늘어 새 패턴이 필요해지면 이 상수들에 추가하고, 반드시 각 패턴이
# "무엇을 거르는지" 주석을 남긴다.
#
# 줄 처리 규칙은 두 종류로 나뉜다.
#   (A) DROP  — 줄 전체가 잔여물이라 통째로 버려도 되는 경우
#                (예: "OOO 기자 abc@def.com"만 있는 줄)
#   (B) TRIM  — 잔여물이 실제 본문 문장 맨 앞에 구분자 없이 붙어버린 경우.
#                줄 전체를 버리면 기사 도입부가 함께 사라지므로 접두어만
#                잘라내고 나머지는 남긴다.
#                (예: "현대경제신문 정준기 기자 | 케이뱅크가 개발 생산성...")
# ---------------------------------------------------------------------------

# --- (A) DROP 패턴 ---------------------------------------------------------

# 이메일 주소. 실측 결과 이메일이 포함된 줄은 예외 없이 기자 서명·사진
# 크레딧이었고 본문 문장과 섞인 사례는 없었다(103건 기준) — 그래서 "줄에
# 이메일이 있으면 통째로 버린다"가 안전하다. 바이라인과 이메일이 서로 다른
# 줄로 쪼개진 경우(예: "전대현 기자" 다음 줄에 "jdh@chosunbiz.com")도 각
# 줄이 이 패턴과 아래 _BYLINE_ALONE_RE에 따로 걸려 개별적으로 사라진다.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# "(매체명 )OOO 기자"만 있고 그 외 내용이 전혀 없는 줄(다음 줄에 이메일이
# 따로 떨어져 있거나, 이메일 없이 서명만 있는 매체).
_BYLINE_ALONE_RE = re.compile(r"^(?:\S{1,15}\s+)?[가-힣]{2,4}\s*기자$")

# 입력/수정 시각 표기: "수정 2026-08-04 11:12:36" / "입력 2026-08-04 11:11:12"
_TIMESTAMP_RE = re.compile(r"^(입력|수정)\s*[:：]?\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(:\d{2})?$")

# 순수 광고 마커 줄("advertisement"만 있는 줄).
_AD_RE = re.compile(r"^advertisement$", re.IGNORECASE)

# 하이픈만 있는 줄. 스크랩 과정에서 남은 빈 불릿(예: "- ")으로, 실제 문장이
# 아니다. 단, "- 실제 제목" 같은 목록형 본문(뉴스 브리핑 기사 등)은 하이픈
# 뒤에 내용이 있으므로 이 패턴에 걸리지 않는다.
_LONE_DASH_RE = re.compile(r"^[-–—]{1,3}$")

# 저작권/무단전재 고지. ⓒ/©/저작권자 표기가 매체마다 다르므로 "무단전재·
# 재배포·재판매" 핵심 어휘 포함 여부로 판정한다.
#   예: "[ⓒ데이터저널리즘의 중심 데이터뉴스 - 무단전재 & 재배포 금지]"
#       "©'5개국어 글로벌 경제신문' 아주경제. 무단전재·재배포 금지"
#       "<저작권자 © 테크홀릭, 무단 전재 및 재배포 금지>"
#       "*재판매 및 DB 금지" (뉴시스 등 통신사 사진 하단)
_COPYRIGHT_PATTERNS = [
    re.compile(r"무단\s*전재"),
    re.compile(r"재배포"),
    re.compile(r"재판매"),
    re.compile(r"copyright.*reserved", re.IGNORECASE),
]

# 사진/그래픽 캡션. "사진=", "그래픽=" 표기는 한국 언론 관행상 캡션에만
# 쓰이므로 줄 안 어디에 있든 그 줄 전체를 캡션으로 간주해 버린다. 실측
# 결과 이 표기가 있는 줄은 모두 그 자체로 완결된 캡션 문장이었고(마침표로
# 끝난 뒤 캡션 태그가 붙는 형태), 뒤 문단 본문과 구분자 없이 이어진 사례는
# 없었다(이미지 확대보기 접두어와 달리 TRIM이 아니라 DROP으로 처리).
#   예: "사진=농협생명" / "[사진=제공]" / "지난 14일 ... 하고 있다. [사진= KB금융그룹 제공]"
#       "토스뱅크의 정보보호 관련 지표 정리 /그래픽=김홍준 기자"
#       "서울 서초구 삼성화재 사옥 전경. [삼성화재 제공]"
#       "사진은 이날 서울 도심에 설치된 은행 ATM기. 2026.5.3 ⓒ 뉴스1 김성진 기자" (통신사 사진 크레딧)
_PHOTO_CAPTION_PATTERNS = [
    re.compile(r"사진\s*제공\s*="),
    re.compile(r"사진\s*="),
    re.compile(r"그래픽\s*="),
    re.compile(r"\[[^\[\]]{0,30}제공\]\s*$"),
    re.compile(r"ⓒ\s*\S+\s+[가-힣]{2,4}\s*(기자|디자이너)\s*$"),
]

# 댓글창 UI 잔여물.
_COMMENT_UI_PATTERNS = [
    re.compile(r"^댓글\s*\(\d+\)$"),
    re.compile(r"자\s*이내로\s*써주세요"),
    re.compile(r"댓글은\s*표시가\s*제한"),
]

# 매체 자체 홍보/구독 유도/제보 CTA.
_PROMO_PATTERNS = [
    re.compile(r"^\[제보\]"),
    re.compile(r"^\[구독\]"),
    re.compile(r"구독해주세요"),
    re.compile(r"제보를\s*기다립니다"),
    re.compile(r"^▶(카카오톡|뉴스\s*홈페이지|이메일)\s*[:：]"),
]

# 신문사 마스트헤드(사업자등록번호·주소·Tel/Fax 등 자기소개 각주) 블록.
#   예: "인터넷신문 등록번호 : 서울, 아02546 ㅣ 등록일 : 2013년 3월 20일 ㅣ 제호 : 메트로신문"
#       "주식회사 메트로미디어 · 서울특별시 종로구 자하문로17길 18 ㅣ Tel : 02. 721. 9800 / Fax : 02. 730. 2882"
#       "사업자등록번호 : 242-88-00131 ISSN : 2635-9219 ㅣ 청소년 보호책임자 및 고충처리인 : 안대성"
# ⚠️ 단순히 "등록번호"만으로 매칭하면 "주민등록번호"(개인정보보호 관련 기사
# 본문에 실제로 등장하는 단어) 문장을 통째로 날리는 사고가 난다(pk=607에서
# 실측 확인). 반드시 매체 자기소개 문맥의 구체적인 접두어와 함께 매칭한다.
_MASTHEAD_PATTERNS = [
    re.compile(r"(인터넷신문|사업자|신문사업)\s*등록번호"),
    re.compile(r"청소년\s*보호\s*책임자"),
    re.compile(r"Tel\s*[:：].*Fax\s*[:：]", re.IGNORECASE),
]

# 추천/관련 기사 위젯 헤더. 이 줄부터 본문 끝까지는 언제나 위젯이므로(103건
# 실측 결과 두 사례 모두 본문 맨 끝에서만 등장) 이 줄을 포함해 이후 전부를
# 버린다. "관련기사" 뒤에 다른 기사의 무관한 헤드라인 목록이 이어지는 식이라
# 개별 줄 패턴으로는 걸러낼 수 없다.
_TRAILING_WIDGET_MARKERS = {"관련기사", "추천 뉴스"}

# --- (B) TRIM 패턴 ----------------------------------------------------------

# 바이라인이 실제 본문 첫 문장과 한 줄에 구분자(|·)로 붙어버린 경우.
#   예: "현대경제신문 정준기 기자 | 케이뱅크가 개발 생산성 향상을 위해..."
# 이메일이 포함된 순수 바이라인 줄은 위 _EMAIL_RE에서 이미 통째로 걸러지므로
# 여기 도달하는 줄은 파이프 뒤에 실제 문장이 남아있는 경우만 남는다.
_BYLINE_PREFIX_RE = re.compile(r"^(?:\S{1,15}\s+)?[가-힣]{2,4}\s*기자\s*[|·]\s*")

# "이미지 확대보기" 버튼 텍스트가 다음 문단 첫 글자와 공백 없이 붙어버린 경우.
#   예: "이미지 확대보기케이뱅크는 한국과 유럽 은행권이 공동 추진하는..."
_IMAGE_BUTTON_PREFIX_RE = re.compile(r"^이미지\s*확대보기")


def _clean_line(stripped_line):
    """한 줄(이미 strip된 상태)에서 스크랩 잔여물을 제거한다.

    반환값이 None이면 줄 전체를 버린다는 뜻이고, 문자열이면 그 문자열을
    (접두어가 잘렸을 수 있는) 본문 줄로 쓴다.
    """
    s = stripped_line

    if _EMAIL_RE.search(s):
        return None
    if _BYLINE_ALONE_RE.match(s):
        return None
    if _TIMESTAMP_RE.match(s):
        return None
    if _AD_RE.match(s):
        return None
    if _LONE_DASH_RE.match(s):
        return None
    for pat in (
        _COPYRIGHT_PATTERNS
        + _PHOTO_CAPTION_PATTERNS
        + _COMMENT_UI_PATTERNS
        + _PROMO_PATTERNS
        + _MASTHEAD_PATTERNS
    ):
        if pat.search(s):
            return None

    s = _BYLINE_PREFIX_RE.sub("", s)
    s = _IMAGE_BUTTON_PREFIX_RE.sub("", s)
    s = s.strip()
    return s or None


@register.filter(name="news_body")
def news_body_filter(text):
    """News.body 원문을 스크랩 잔여물 제거 + 줄 단위 문단 분리해 안전한 HTML로 바꾼다.

    - News.body는 문단이 줄바꿈 하나(\\n)로 구분돼 있어(검증 뉴스 103건 중
      87건이 단일 개행만, 빈 줄 없음) 표준 `linebreaks` 필터(빈 줄 기준으로
      <p> 생성)를 쓰면 본문 전체가 <p> 하나가 된다. 여기서는 "줄 하나 =
      문단 하나"로 렌더링한다. 빈 줄이 있는 경우도 같은 처리로 자연히
      흡수된다(빈 줄은 버려짐).
    - XSS 방지: 각 줄은 escape()를 거친 뒤 <p> 태그로만 감싼다(마크다운이
      아니라 평문이므로 이스케이프만으로 충분, apps/reports/templatetags의
      markdown 필터와 달리 bleach는 불필요).
    """
    if not text:
        return ""

    paragraphs = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s in _TRAILING_WIDGET_MARKERS:
            break
        cleaned = _clean_line(s)
        if cleaned:
            paragraphs.append(cleaned)

    html = "".join(f"<p>{escape(p)}</p>" for p in paragraphs)
    return mark_safe(html)
