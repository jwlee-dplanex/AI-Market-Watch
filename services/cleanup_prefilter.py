"""조사 2단계(뉴스 정리) 사전 차단 규칙 — docs/planning.md "2단계 비용 절감 정책:
무엇을 LLM에 보내지 않을 것인가"(2026-09-16 신설) A안 구현.

규칙 한 줄: 제목과 본문 어디에도 AI 계열 낱말이 0회인 기사는 LLM에 보내지 않는다.

🔴 이 판정 함수(`should_prefilter_delete`) 하나를 실행 경로(services/runner.py
_run_cleanup())와 회귀 검사(apps/setting/views.py 확정 뷰)가 함께 쓴다 — 두 벌이
되면 그 자리에서 갈린다(같은 문서 "구조 제안").

낱말 목록은 사용자가 실측으로 확정한 열다섯 개다(A.I.는 제외 — 검증 0건, 삭제 0건,
한국 기사에서 안 쓰는 표기). 늘리거나 줄이지 않는다.
"""

from services.collector import _find_alias_positions

# 🔴 확정된 목록(2026-09-16). PM이 반증 0건 검사로 확정했다 — 추가 후보 22개를
# 시험했으나 유일근거가 전부 0건이었고 넣으면 절감만 깎였다(115건 → 109건).
AI_KEYWORDS = [
    "AI", "AX", "LLM", "GPT",
    "인공지능", "머신러닝", "기계학습", "딥러닝",
    "생성형", "거대언어모델", "챗GPT",
    "에이전트", "에이전틱", "알고리즘", "자동화",
]

# 목록이 바뀌면 이 값도 함께 올린다 — RunProposal.criterion_code에 그대로 박혀
# "무엇으로 걸렀는지"가 기록에 남는다(RunJob.prompt_version과 같은 목적,
# docs/planning.md 같은 절 8번 PE 인계).
KEYWORD_LIST_VERSION = "2026-09-16"
CRITERION_CODE = f"P-AI0-{KEYWORD_LIST_VERSION}"

# 크롤 실패 방어(같은 문서 4-5번) — 검색 API의 description만 남은 짧은 본문에는
# 규칙을 적용하지 않는다. "의심되면 LLM으로"가 방향이다.
BODY_LENGTH_THRESHOLD = 300

# 🔴 문구는 PD가 정본이다(docs/design.md "SET-010 · 실행" 21차 개정 ⑦번) — 그대로
# 옮긴다. RunProposal.reason에 저장돼 확정 뒤 DeletedNewsRecord.reason까지 그대로
# 남는 값이라 화면(뷰)에서 따로 만들지 않고 여기 한 곳에 둔다.
REASON = "제목과 본문에 AI 관련 낱말이 한 번도 없어요"


def has_no_ai_keyword(title: str, body: str) -> bool:
    """title·body를 합쳐 AI_KEYWORDS 중 하나라도 단어 경계를 지키며 등장하면 False,
    한 번도 등장하지 않으면 True.

    services/collector.py의 _find_alias_positions()를 그대로 재사용한다 — 그 함수는
    이미 소문자로 바뀐 텍스트를 요구하므로 여기서 먼저 .lower()를 거친다."""
    lower_text = f"{title}\n{body}".lower()
    return not any(_find_alias_positions(lower_text, keyword) for keyword in AI_KEYWORDS)


def should_prefilter_delete(title: str, body: str) -> bool:
    """코드가 LLM 없이 바로 삭제 제안을 낼지 판정한다.

    본문이 BODY_LENGTH_THRESHOLD자 미만이면 크롤 실패를 의심해 규칙을 건너뛰고
    False를 반환한다(의심되면 LLM으로) — 이 경우 호출부는 평소대로 LLM 판정으로
    넘긴다."""
    if len(body) < BODY_LENGTH_THRESHOLD:
        return False
    return has_no_ai_keyword(title, body)
