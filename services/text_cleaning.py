import re

# ---------------------------------------------------------------------------
# News 원문 스크랩 잔여물 필터 (2026-08-05)
#
# 수집기(services/collector.py)가 기사 본문만 깔끔하게 가져오지 못하고 매체
# 사이트의 기자 서명, 저작권 문구, 사진 캡션, 댓글 UI, 하단 "관련기사" 위젯 등
# 스크랩 잔여물을 함께 담아온다. News.body 원문은 절대 고치지 않는다(매체마다
# 형식이 계속 바뀔 텐데, 원문이 남아 있어야 규칙을 고쳤을 때 다시 적용할 수
# 있다) — 이 잔여물 제거는 원문을 "쓰는 쪽"에서 필요할 때만 통과시켜 쓴다.
#
# 두 곳에서 이 필터를 공유한다.
#   1. apps/news/templatetags/news_extras.py — NEWS-002 화면에 본문을 보여줄 때
#   2. services/collector.py — 기업/기술 주제 태깅 대상 텍스트를 만들 때
# 어느 한쪽만 고치면 둘이 어긋나므로, 잔여물 패턴은 반드시 이 모듈 하나에만
# 정의하고 양쪽이 가져다 쓴다.
#
# 원칙: "의심스러우면 남긴다". 본문(또는 태깅 대상 텍스트)이 과하게 잘려나가는
# 사고가 잔여물이 남는 것보다 훨씬 나쁘다. 검증된 뉴스 103건(1,987줄)을 실측해
# 아래 패턴을 뽑았다. 매체가 늘어 새 패턴이 필요해지면 이 상수들에 추가하고,
# 반드시 각 패턴이 "무엇을 거르는지" 주석을 남긴다.
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

# 사진 크레딧이 대괄호 없이 "회사명 제공" 단독으로 오는 경우.
#   예: "티오리 제공"
# 쉼표·조사 없이 회사명 한 덩어리 + "제공"으로만 끝나는 아주 짧은 줄만 잡는다.
# 실제 본문 문장도 "...제공"으로 끝나는 경우가 있어(예: "◆카카오뱅크, 제휴
# 금융사와 함께 우대금리 제공") 앞에 쉼표·조사가 없고 전체가 10자 이내인
# 경우로 좁혀 그런 문장과 겹치지 않게 한다.
_PHOTO_CREDIT_ALONE_RE = re.compile(r"^[가-힣A-Za-z0-9]{1,10}\s*제공$")

# 신문사 마스트헤드(사업자등록번호·주소·Tel/Fax 등 자기소개 각주) 블록.
#   예: "인터넷신문 등록번호 : 서울, 아02546 ㅣ 등록일 : 2013년 3월 20일 ㅣ 제호 : 메트로신문"
#       "주식회사 메트로미디어 · 서울특별시 종로구 자하문로17길 18 ㅣ Tel : 02. 721. 9800 / Fax : 02. 730. 2882"
#       "사업자등록번호 : 242-88-00131 ISSN : 2635-9219 ㅣ 청소년 보호책임자 및 고충처리인 : 안대성"
# ⚠️ 단순히 "등록번호"만으로 매칭하면 "주민등록번호"(개인정보보호 관련 기사
# 본문에 실제로 등장하는 단어) 문장을 통째로 날리는 사고가 난다(pk=607에서
# 실측 확인). 반드시 매체 자기소개 문맥의 구체적인 접두어와 함께 매칭한다.
#   예: "대한민국 보험과 은행, 금융을 읽는 [한국보험신문]" (기사 맨 끝, 바이라인
#       바로 뒤에 붙는 매체 태그라인. pk=550에서 소제목 판정 규칙 검증 중 발견 —
#       쉼표를 포함한 짧고 비종결형 문장이라 소제목으로 잘못 커질 뻔했다.)
_MASTHEAD_PATTERNS = [
    re.compile(r"(인터넷신문|사업자|신문사업)\s*등록번호"),
    re.compile(r"청소년\s*보호\s*책임자"),
    re.compile(r"Tel\s*[:：].*Fax\s*[:：]", re.IGNORECASE),
    re.compile(r"읽는\s*\[[^\[\]]{1,20}\]\s*$"),
]

# 추천/관련 기사 위젯 헤더. 이 줄부터 본문 끝까지는 언제나 위젯이므로(103건
# 실측 결과 두 사례 모두 본문 맨 끝에서만 등장) 이 줄을 포함해 이후 전부를
# 버린다. "관련기사" 뒤에 다른 기사의 무관한 헤드라인 목록이 이어지는 식이라
# 개별 줄 패턴으로는 걸러낼 수 없다.
_TRAILING_WIDGET_MARKERS = {"관련기사", "추천 뉴스"}

# 헤더 문구 없이 하이픈 목록만 본문 맨 끝에 이어지는 "관련기사" 위젯(태깅
# 오탐 실측, 2026-08-05: News pk=751 — 카카오페이증권 기자간담회 단독 기사
# 끝에 "- KB국민은행, ...", "- 하나은행, ..." 등 무관한 다른 기사 헤드라인
# 9개가 이어져 IBK기업은행·KB국민은행·우리은행·토스·하나은행이 전부 잘못
# 태깅됐다. pk=1092도 같은 형태로 완전히 무관한 연예/사회 헤드라인이 붙는다).
# 위 _TRAILING_WIDGET_MARKERS와 달리 "관련기사"라는 헤더 자체가 없어서 줄
# 내용만으로 판단해야 한다 — clean_lines()의 _find_trailing_bullet_cutoff가
# "실제 문장이 최소 한 번 나온 뒤(본문이 시작된 뒤) 하이픈 줄이 나오고, 그
# 하이픈 줄부터 끝까지 전부 하이픈 줄인가"를 본다. 뉴스 브리핑처럼 기사
# 전체가 하이픈 목록인 경우(문서 맨 앞부터 하이픈이라 "본문이 시작된 뒤"
# 조건을 만족하지 못함)와 구분하기 위해서다.
_BULLET_PREFIX_CHARS = ("-", "–", "—")

# "시리즈 목차" 잔여 줄. 언론사가 연재 기사 본문 안에 같은 시리즈의 다른 회차
# 제목을 "[시리즈명<circled-number>] 회사명, '문구'" 형식으로 그대로 끼워
# 넣는다(태깅 오탐 실측, 2026-08-05: News pk=343 — 신한금융 편(②) 본문에
# "[금융권 인공지능 활용①] KB금융, 'KB with AI' 본격화"가 그대로 섞여 들어와
# KB국민은행이 잘못 태깅됐다. pk=958도 같은 시리즈의 다른 회차라 ①~④ 4줄이
# 한꺼번에 섞여 있다). 이 기사 자신의 제목과 같은 문장이 본문 첫 줄에 그대로
# 중복되는 경우도 이 패턴에 걸리지만, 그 회사명은 이미 News.title(필터 대상
# 아님)에도 있으므로 걸러도 태깅에 영향이 없다.
# 원문자(①-⑩)는 순서를 매기는 용도로만 쓰이고 일반 문장에 거의 등장하지
# 않아(전수 스캔 결과 103건 중 원문자가 등장한 3건 중 이 시리즈 목차가 아닌
# 유일한 사례는 pk=1173 "AI 에이전트는 ①개별 초단기채에..."처럼 대괄호 없이
# 문장 중간에 등장 — 대괄호로 줄 전체를 감싼 경우만 매칭하므로 걸리지 않는다.
_SERIES_TOC_RE = re.compile(r"^\[[^\[\]]*[①②③④⑤⑥⑦⑧⑨⑩][^\[\]]*\]")

# --- (B) TRIM 패턴 ----------------------------------------------------------

# 바이라인이 실제 본문 첫 문장과 한 줄에 구분자(|·)로 붙어버린 경우.
#   예: "현대경제신문 정준기 기자 | 케이뱅크가 개발 생산성 향상을 위해..."
# 이메일이 포함된 순수 바이라인 줄은 위 _EMAIL_RE에서 이미 통째로 걸러지므로
# 여기 도달하는 줄은 파이프 뒤에 실제 문장이 남아있는 경우만 남는다.
_BYLINE_PREFIX_RE = re.compile(r"^(?:\S{1,15}\s+)?[가-힣]{2,4}\s*기자\s*[|·]\s*")

# "이미지 확대보기" 버튼 텍스트가 다음 문단 첫 글자와 공백 없이 붙어버린 경우.
#   예: "이미지 확대보기케이뱅크는 한국과 유럽 은행권이 공동 추진하는..."
_IMAGE_BUTTON_PREFIX_RE = re.compile(r"^이미지\s*확대보기")

# "[매체=이름 기자]"가 본문 문단 맨 앞에 구분자 없이 붙어버린 경우.
#   예: "[미디어펜=류준현 기자] 금융권이 '인공지능 에이전트(AI agent)' 도입으로..."
#       "[헤럴드경제=배문숙 기자]정부가 성장 잠재력이 높은..." (공백 없이 바로 붙음)
# 이 접두어만 있고 뒤에 문장이 없는 줄(예: "[소비자가만드는신문=장경진 기자]")은
# 접두어를 잘라내면 빈 문자열이 남아 아래 공통 처리(strip 후 빈 값이면 버림)로
# 자연히 사라진다.
_MEDIA_BYLINE_PREFIX_RE = re.compile(r"^\[[^\[\]]{1,20}=[^\[\]]{1,20}(기자|특파원)\]\s*")


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
    if _PHOTO_CREDIT_ALONE_RE.match(s):
        return None
    if _SERIES_TOC_RE.match(s):
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
    s = _MEDIA_BYLINE_PREFIX_RE.sub("", s)
    s = _IMAGE_BUTTON_PREFIX_RE.sub("", s)
    s = s.strip()
    return s or None


# 문장 종결 판정(마지막 문단이 "진짜 문장"으로 끝났는지). 아래 트레일링
# 하이픈 위젯 탐지에서 "본문이 이미 시작됐는가"를 가르는 데 쓴다. 따옴표·
# 괄호를 먼저 벗겨낸 뒤 마지막 글자를 본다 — apps/news/templatetags의 소제목
# 판정 규칙과 판정 방식이 같아야 하므로(문장 종결 여부는 관심사가 하나뿐이다)
# 여기 한 곳에만 두고 news_extras.py도 이 함수를 가져다 쓴다.
_TRAILING_QUOTE_RE = re.compile(r"[\"'“”‘’()\[\]『』「」《》]+$")
_TERMINAL_CHARS = (".", "!", "?", "다", "요")


def ends_with_terminal_punct(s):
    t = _TRAILING_QUOTE_RE.sub("", s).rstrip()
    return bool(t) and t[-1] in _TERMINAL_CHARS


def _is_bullet_line(s):
    return s.startswith(_BULLET_PREFIX_CHARS)


def _find_trailing_bullet_cutoff(lines):
    """헤더 문구 없는 하이픈 목록 위젯(News pk=751, 1092 실측)의 시작 인덱스를 찾는다.

    "본문이 시작된 뒤(=문장 종결로 끝나는 문단을 한 번이라도 지난 뒤)" 나온
    하이픈 줄부터, 문서 끝까지 남은 줄이 전부 하이픈 줄이면 그 지점부터
    위젯으로 본다. 두 조건 다 필요하다.
      - "본문이 시작된 뒤"만 검사: 뉴스 브리핑처럼 기사 전체가 하이픈 목록인
        경우(맨 처음부터 하이픈이라 이 조건에서 걸러진다)까지 위젯으로 오인해
        기사 전체를 날리는 사고를 막는다.
      - "끝까지 전부 하이픈"만 검사: 본문 중간에 하이픈 인용/목록이 한 줄
        섞였다가 다시 일반 문단으로 돌아오는 경우까지 위젯으로 오인하는 걸
        막는다(위젯은 항상 문서 맨 끝에서만 관측됐다).
      - 하이픈 줄이 최소 2개는 이어져야 한다(단발성 하이픈 줄 하나는 실제
        본문 문장일 수 있어 위젯이라 보기엔 신호가 약하다).
    없으면 None을 반환한다(=자르지 않는다).
    """
    body_started = False
    for i, s in enumerate(lines):
        if body_started and _is_bullet_line(s):
            rest = lines[i:]
            if len(rest) >= 2 and all(_is_bullet_line(x) for x in rest):
                return i
        if ends_with_terminal_punct(s):
            body_started = True
    return None


def clean_lines(text):
    """원문에서 스크랩 잔여물을 제거한 줄(문단) 리스트를 반환한다.

    NEWS-002 화면 렌더링(apps/news/templatetags/news_extras.py)과 기업/기술
    주제 태깅(services/collector.py) 양쪽이 이 함수 하나를 공유한다. 각 줄이
    통째로 버려지는지(DROP), 접두어만 잘리는지(TRIM)는 _clean_line이 판정하고,
    다음 두 경우는 그 줄부터 문서 끝까지를 통째로 버린다.
      - "관련기사"/"추천 뉴스" 위젯 헤더가 있는 경우
      - 헤더 없이 하이픈 목록만 문서 끝까지 이어지는 경우(_find_trailing_bullet_cutoff)
    """
    if not text:
        return []
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    cutoff = len(lines)
    for i, s in enumerate(lines):
        if s in _TRAILING_WIDGET_MARKERS:
            cutoff = i
            break
    bullet_cutoff = _find_trailing_bullet_cutoff(lines[:cutoff])
    if bullet_cutoff is not None:
        cutoff = bullet_cutoff

    paragraphs = []
    for s in lines[:cutoff]:
        cleaned = _clean_line(s)
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


def clean_text_for_matching(text):
    """기업/기술 주제 별칭 매칭 등 "정제된 평문"이 필요한 곳에서 쓰는 진입점.

    clean_lines()가 돌려준 문단들을 줄바꿈으로 다시 이어붙인다. News.body
    저장값 자체는 건드리지 않고, 매칭에만 이 반환값을 쓴다.
    """
    return "\n".join(clean_lines(text))
