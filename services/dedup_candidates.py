"""중복 후보를 코드로 좁히는 순수 함수 — docs/planning.md 2-6 "후보를 코드로 좁히고
LLM은 확인만 한다" 구현.

배경(실측, 2026-09-17 심야): 창 안 검증분 전량(47건)을 한 호출로 LLM에 보내면 묶음이
0개 나왔다. 같은 재료를 사건별로 3건·9건씩 나눠 보내면 둘 다 정확히 잡혔다. 이 모듈은
"그 크기로 나눠 주는" 역할만 한다 — LLM 호출은 하지 않는다(배선은 다음 라운드).

계약: find_duplicate_candidates(news_items) — 「창 안 기사들 → 후보 묶음 목록」.
news_items는 .pk / .title / .body 속성을 갖는 객체 목록(News 인스턴스를 그대로 넣을 수
있고, 테스트에서는 같은 속성의 더미 객체를 넣어도 된다). 내부가 토큰 겹침이든 나중에
코사인 유사도로 바뀌든 이 계약(바깥에서 본 입출력 모양)은 그대로 유지한다(2-7-(b)).

🔴 신호는 둘이고 OR다(2-6-(a)) — 사건 지문(본문 도입부의 복합명사 덩어리) 또는 숫자
토큰(숫자+단위) 중 하나만 겹쳐도 후보다. 제목·기업 태그·발행일·기술 주제는 신호가
아니다(종전 기각 상속).

🔴 신호 추출은 본문 전량(코드라 0원). LLM에 보내는 절단은 이 모듈이 하지 않는다
(2-6-(b)) — 호출부가 자기 절단 로직으로 별도로 처리한다.

🔴 상한은 경보선이지 차단선이 아니다(2-6-(c)) — 넘어도 쪼개거나 버리지 않고 그대로
반환하며 over_soft_cap 플래그만 켠다.

🔴 흔한 값은 사전(하드코딩 목록)이 아니라 창 안 빈도로 제외한다(2-6-(a)) — 어떤
신호든 이 창 안 기사의 절반 이상(그리고 최소 3건 이상)에서 나타나면 변별력이 없다고
보고 후보 판정에서 뺀다. 판정에는 반영하지만 화면에 "무엇이 흔해서 빠졌는지" 보고할
수 있도록 그 목록도 함께 반환한다.
"""
import re
from dataclasses import dataclass, field

from services.text_cleaning import clean_lines, clean_text_for_matching

# ---------------------------------------------------------------------------
# 1단계 정규화 — 비교용 사본에만 적용한다(2-7-(h)). News.body/title은 절대 건드리지
# 않는다. 숫자 토큰과 따옴표 안 인용문은 절대 지우지 않는다 — 이 모듈이 뒤에서 그
# 둘을 신호로 쓰기 때문에, 정규화가 먼저 돌아도 신호가 살아 있어야 한다.
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")

# 장식용 특수문자 — 기자명/언론사명(clean_text_for_matching이 이미 제거)과 별개로
# 본문에 흔한 불릿·구분 기호. 숫자·단위·따옴표(", ", '', 「」, 『』, 《》, 〈〉)는
# 이 목록에 없다 — 절대 지우지 않는다.
_DECORATIVE_CHARS_RE = re.compile(r"[▶▷◀◁■□◆◇●○◎☆★※◈►◄∎‣~^_=|#@&◇]+")

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_for_comparison(text):
    """비교용 사본을 만든다. 기자명·언론사명·꼬리말(clean_text_for_matching이 이미
    처리)에 더해 HTML 태그·장식 특수문자·중복 공백을 정리한다. 원문(News.body)을
    고치지 않고 새 문자열을 반환한다."""
    if not text:
        return ""
    cleaned = clean_text_for_matching(text)
    cleaned = _HTML_TAG_RE.sub(" ", cleaned)
    cleaned = _DECORATIVE_CHARS_RE.sub(" ", cleaned)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


# ---------------------------------------------------------------------------
# 신호 1 — 숫자 토큰(숫자 + 단위). 본문 전량에서 뽑는다.
# ---------------------------------------------------------------------------

# 크기 접두(조/억/만/천)는 0회 이상 반복될 수 있고("5273억원"), 뒤에 단위가 없어도
# 그 자체로 유효한 토큰이다("500만" — MAU 500만). 크기 접두도 단위도 전혀 없는
# 맨 숫자("2026", "85")는 실측(카카오 IR "85%")에서 보듯 %가 붙어야 신호가 되므로
# 제외한다 — 순서번호·연도 맨 숫자는 어디에나 있어 변별력이 없다.
_NUMBER_MAGNITUDE = "조|억|만|천"
_NUMBER_UNIT = (
    "%|퍼센트|원|명|개|건|장|곳|호|배|위|점|평|톤|년|월|일|시간|분|초|"
    "대|척|회|차|세대|주|년간|개월|주년"
)
_NUMBER_TOKEN_RE = re.compile(
    rf"\d[\d,]*(?:\.\d+)?(?:{_NUMBER_MAGNITUDE}|{_NUMBER_UNIT}){{1,3}}"
)

# 🔴 실측(2026-09-17, 최근 7일 창 54건)으로 드러난 함정 하나 — 날짜 표기("15일",
# "16일", "2027년", "10월")는 크기 접두 없이 「연/월/일」 단위만 붙어도 위 정규식에
# 걸리고, 거의 모든 기사가 날짜를 언급하므로 이 형태만으로 창 전체가 한 묶음으로
# 이어졌다(17/54, 15/54 등). 이것은 "이 값이 흔하다"는 사전 지식이 아니라 "달력
# 표기는 크기(양)를 나타내지 않는다"는 문법 범주 판정이다 — 그래서 흔한 값 창 안
# 빈도 판정(아래 _find_common_values)보다 먼저, 크기 접두가 없는 순수 연/월/일
# 표기를 애초에 숫자 토큰에서 제외한다. "500만원"처럼 크기 접두가 붙으면 여전히
# 신호다.
_PURE_CALENDAR_RE = re.compile(r"^\d{1,4}(?:년|월|일)$")

# 🔴 실측으로 드러난 함정 둘 — "2개", "13개", "1차", "40%", "300명"처럼 크기 접두
# (조/억/만/천) 없는 작은 숫자 + 흔한 단위는 서로 무관한 기사 사이에서도 우연히
# 같은 값이 나온다(예: 3521과 3758이 아무 관계가 없는데 "300명"·"1000명"·"2억"이
# 동시에 겹쳐 하나로 묶였다). 크기 접두가 붙으면("7만장", "5273억원") 이미 값 자체가
# 커서 우연히 겹칠 확률이 낮으므로 그대로 신호로 쓰지만, 접두가 없으면 값이 세 자리
# 이상이거나(예: "512장", "528만명"은 만이 접두라 이미 통과) 소수점이 있는 경우로
# 좁힌다(예: "162.97%"). "2개"·"40%"·"1차"류의 우연한 잡음을 이렇게 걸러낸다.
_HAS_MAGNITUDE_RE = re.compile(rf"^\d[\d,]*(?:\.\d+)?(?:{_NUMBER_MAGNITUDE})")
_NUMERIC_PREFIX_RE = re.compile(r"^\d[\d,]*(?:\.\d+)?")


def _is_distinctive_number(token):
    if _HAS_MAGNITUDE_RE.match(token):
        return True
    numeric_prefix = _NUMERIC_PREFIX_RE.match(token).group()
    if "." in numeric_prefix:
        return True
    return len(numeric_prefix.replace(",", "")) >= 3


def extract_number_tokens(normalized_text):
    """정규화된 본문 전량에서 숫자+단위 토큰 집합을 뽑는다. 같은 토큰이 본문에 여러
    번 나와도 신호는 "이 기사에 있다/없다"만 필요하므로 집합으로 반환한다."""
    tokens = set(_NUMBER_TOKEN_RE.findall(normalized_text))
    tokens = {t for t in tokens if not _PURE_CALENDAR_RE.match(t)}
    return {t for t in tokens if _is_distinctive_number(t)}


# ---------------------------------------------------------------------------
# 신호 2 — 사건 지문(본문 도입부의 복합명사 덩어리). 이 저장소에 형태소 분석기가
# 없으므로(services/cleanup_prefilter.py와 같은 사정) 완전한 명사구 추출이 아니라
# 실측 근거(planning.md 2-3·2-6)에 나온 형태 — 영문 약어 단독 토큰(ADAS, MAU, PoC
# 등)과 한글 인접 2어절 묶음 — 을 후보로 삼는다. 제목은 신호가 아니므로 title은
# 여기서 쓰지 않는다.
# ---------------------------------------------------------------------------

# 도입부 — 첫 문단만 본다("본문 도입부"). clean_lines()가 스크랩 잔여물(바이라인 등)을
# 이미 제거하므로 그 뒤 첫 문단이 실제 기사 도입부다.
_INTRO_PARAGRAPHS = 1

# 영문 약어/로마자 조어(ADAS, MAU, PoC, LLM, GPT 등). 대소문자 섞여도 잡히게 하되
# 🔴 최소 3자로 둔다 — 실측(2026-09-17, 최근 7일 창 54건)에서 "AI"(2자)만 16/54
# (29.6%)에 등장해 서로 무관한 기사 전량을 하나로 묶었다. 이 저장소의 주제 자체가
# "AI 관련 뉴스"라 "AI"는 이 창에서만 흔한 값이 아니라 어느 창에서도 흔한 값일
# 수밖에 없다 — 창 안 빈도로는 가려낼 수 없는(그때그때 다른 값이 아니라 이 서비스가
# 존재하는 이유 자체인) 경우라, 사전 목록이 아니라 "2자짜리 약어는 변별력이 없다"는
# 구조적 기준으로 대신한다. ADAS·MAU·PoC·LLM·GPT는 전부 3자 이상이라 그대로 산다.
_ACRONYM_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{2,9}$")

# 한글 어절 끝의 조사를 벗겨 표현이 살짝 달라도(예: "카카오가"/"카카오는") 겹치게
# 한다. 길이 긴 조사부터 검사해야 짧은 조사가 먼저 걸려 잘못 잘리지 않는다(예:
# "에서"를 "서"보다 먼저 검사).
_JOSA_SUFFIXES = sorted(
    ["에서", "에게", "으로", "이라도", "라도", "이나", "까지", "부터", "처럼",
     "같이", "조차", "마저", "밖에", "이며", "이고", "이라고", "라고", "이란",
     "란", "은", "는", "이", "가", "을", "를", "의", "와", "과", "도", "만", "나", "고"],
    key=len, reverse=True,
)


def _strip_trailing_josa(token):
    for suf in _JOSA_SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= 2:
            return token[: -len(suf)]
    return token


_TOKEN_SPLIT_RE = re.compile(r"[\s/·,]+")
_STRIP_PUNCT_RE = re.compile(r"^[\"'“”‘’「」『』《》〈〉()\[\]{}.,·]+|[\"'“”‘’「」『』《》〈〉()\[\]{}.,·]+$")

# 🔴 실측으로 드러난 함정 셋 — services/text_cleaning.py의 바이라인 패턴 두 종("...기자 |
# 본문", "[매체=기자] 본문")이 못 잡는 괄호 표기("(시사캐스트, SISACAST=이민선 기자)
# 본문", "(서울=연합뉴스) 이름 기자 = 본문")가 실제로 있었다. 그 매체명·기자명이
# "사건 지문"으로 오인돼 같은 통신사·매체 기사끼리(무관한 사건인데도) 묶이는 사고가
# 났다(SISACAST 5건). services/text_cleaning.py(공용 모듈)는 고치지 않는다 — 이
# 모듈의 신호 추출에만 필요한 좁은 보정이라 여기 국소적으로만 덧댄다.
_LOCAL_BYLINE_PAREN_RE = re.compile(r"^[\(\[][^\)\]]{1,40}(=|기자|특파원)[^\)\]]{0,20}[\)\]]\s*")
_LOCAL_BYLINE_EQ_RE = re.compile(r"^[가-힣]{2,4}\s*기자\s*=\s*")


def _strip_local_byline_leak(intro_text):
    text = intro_text
    while True:
        new_text = _LOCAL_BYLINE_PAREN_RE.sub("", text)
        new_text = _LOCAL_BYLINE_EQ_RE.sub("", new_text)
        if new_text == text:
            return new_text
        text = new_text


def _tokenize_intro(intro_text):
    intro_text = _strip_local_byline_leak(intro_text)
    tokens = []
    for raw in _TOKEN_SPLIT_RE.split(intro_text):
        t = _STRIP_PUNCT_RE.sub("", raw)
        if t:
            tokens.append(t)
    return tokens


def extract_event_fingerprints(body):
    """본문 도입부(첫 문단)에서 사건 지문 후보 집합을 뽑는다.

    - 영문 약어/로마자 조어(2자 이상)는 단독으로도 지문이 된다(ADAS, MAU 등 —
      매체를 갈아도 그대로 복사되는 값).
    - 그 외 어절은 조사를 벗긴 뒤 인접 2어절을 이어 붙인 바이그램만 지문으로
      본다. 단일 한글 명사는("이미지", "결제" 등) 너무 흔해 단독으로는 변별력이
      없다 — 2-3 실측이 강한 신호로 지목한 것도 항상 복합("PoC/실증", "이미지
      판독")이었다.
    """
    if not body:
        return set()
    paragraphs = clean_lines(body)[:_INTRO_PARAGRAPHS]
    if not paragraphs:
        return set()
    intro = normalize_for_comparison("\n".join(paragraphs))
    tokens = _tokenize_intro(intro)

    fingerprints = set()
    stems = []
    for tok in tokens:
        if _ACRONYM_RE.match(tok):
            fingerprints.add(tok)
            stems.append(tok)
        else:
            stems.append(_strip_trailing_josa(tok))

    for a, b in zip(stems, stems[1:]):
        if len(a) >= 2 and len(b) >= 2:
            fingerprints.add(f"{a} {b}")

    return fingerprints


# ---------------------------------------------------------------------------
# 흔한 값 제외 — 사전(하드코딩 목록) 대신 창 안 빈도로 판정한다(2-6-(a)). 절반 이상
# *그리고* 최소 3건 이상 나타나는 신호는 변별력이 없다고 본다. 최소 건수 조건이
# 없으면 창이 2건뿐일 때 겹치는 신호가 전부(=100%) "흔한 값"으로 잘못 걸린다.
# ---------------------------------------------------------------------------
COMMON_VALUE_MIN_COUNT = 3
COMMON_VALUE_MAX_SHARE = 0.5


def _find_common_values(signal_to_ids):
    total = len({nid for ids in signal_to_ids.values() for nid in ids})
    common = set()
    if total == 0:
        return common
    for signal, ids in signal_to_ids.items():
        count = len(ids)
        if count >= COMMON_VALUE_MIN_COUNT and count / total >= COMMON_VALUE_MAX_SHARE:
            common.add(signal)
    return common


# ---------------------------------------------------------------------------
# 후보 묶음 — Union-Find로 신호를 공유하는 기사끼리 연결한다. 상한은 경보선이다
# (2-6-(c)) — 넘어도 쪼개거나 버리지 않는다. 실측 근거(2026-09-15, planning.md
# 2-6-(c))의 KB금융 회장 인선 21건이 기준이다 — 그보다 살짝 낮게 잡아야 21건짜리
# 진짜 사건도 "경보"로 잡힌다(상한을 21보다 높게 잡으면 그 사건은 조용히 상한 밑을
# 지나가 아무 표시 없이 넘어간다 — 이 값의 존재 이유 자체가 "커도 표시는 한다"이므로
# 그 표시가 놓치면 안 되는 바로 그 예시를 놓치는 꼴이 된다).
CANDIDATE_GROUP_SOFT_CAP = 20


@dataclass
class CandidateGroup:
    news_ids: list = field(default_factory=list)
    matched_signals: set = field(default_factory=set)
    over_soft_cap: bool = False


class _UnionFind:
    def __init__(self, ids):
        self.parent = {i: i for i in ids}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def find_duplicate_candidates(news_items):
    """창 안 기사들 → 후보 묶음 목록.

    news_items: .pk, .title(쓰지 않음), .body 속성을 갖는 객체 목록. 반환값은
    CandidateGroup 목록(단독 기사·신호 없는 기사는 포함하지 않는다 — 후보는
    "묶음"만 의미가 있다). 후보 0개(=반환 목록이 빈 리스트)면 호출부가 LLM을
    부르지 않는다는 뜻이고, 그 판단은 이 함수의 반환값만으로 내릴 수 있다
    (2-6-(d) "미호출을 실패·0건과 구분해 기록"은 호출부 책임).

    🔴 신호는 본문 전량에서 뽑는다. 이 함수는 LLM에 보낼 절단을 하지 않는다 —
    그건 호출부(다음 라운드)의 일이다(2-6-(b)).
    """
    items = list(news_items)
    if len(items) < 2:
        return []

    fingerprint_to_ids = {}
    number_to_ids = {}
    news_signals = {}

    for item in items:
        normalized_body = normalize_for_comparison(item.body)
        fingerprints = extract_event_fingerprints(item.body)
        numbers = extract_number_tokens(normalized_body)
        news_signals[item.pk] = (fingerprints, numbers)
        for fp in fingerprints:
            fingerprint_to_ids.setdefault(fp, set()).add(item.pk)
        for num in numbers:
            number_to_ids.setdefault(num, set()).add(item.pk)

    common_fingerprints = _find_common_values(fingerprint_to_ids)
    common_numbers = _find_common_values(number_to_ids)

    uf = _UnionFind([item.pk for item in items])
    # signal -> 그 신호로 실제 연결된(=흔한 값이 아니고 2건 이상 공유하는) 기사 id 집합
    effective_signal_ids = {}

    for fp, ids in fingerprint_to_ids.items():
        if fp in common_fingerprints or len(ids) < 2:
            continue
        effective_signal_ids[("fingerprint", fp)] = ids
        ids_list = list(ids)
        for other in ids_list[1:]:
            uf.union(ids_list[0], other)

    for num, ids in number_to_ids.items():
        if num in common_numbers or len(ids) < 2:
            continue
        effective_signal_ids[("number", num)] = ids
        ids_list = list(ids)
        for other in ids_list[1:]:
            uf.union(ids_list[0], other)

    groups_by_root = {}
    for item in items:
        root = uf.find(item.pk)
        groups_by_root.setdefault(root, []).append(item.pk)

    candidates = []
    for root, ids in groups_by_root.items():
        if len(ids) < 2:
            continue
        matched = {
            signal for signal, sig_ids in effective_signal_ids.items()
            if sig_ids & set(ids)
        }
        candidates.append(
            CandidateGroup(
                news_ids=sorted(ids),
                matched_signals={f"{kind}:{value}" for kind, value in matched},
                over_soft_cap=len(ids) > CANDIDATE_GROUP_SOFT_CAP,
            )
        )

    return candidates
