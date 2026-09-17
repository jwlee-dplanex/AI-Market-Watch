"""SET-006 「실행 이력과 비용」이 쓰는 LLM 비용 계산 (docs/design.md SET-006 1차 개정 절,
2026-09-16). 단가와 환율을 한 곳에 모아, 모델이나 환율이 바뀌면 이 파일 한 곳과
templates/setting/logs.html의 각주 문장만 같이 고치면 되게 한다.

🔴 Haiku 4.5 단가다(config/settings/base.py BEDROCK_MODEL_SMART가 지금 비용 때문에
Haiku를 가리키고 있는 것과 같은 맥락). Sonnet으로 되돌리면 이 단가도 함께 갱신해야 한다.
🔴 환율은 1,400원 고정이다(사용자 지시) — 실시간 환율 API를 붙이지 않는다.

🔴 cache_write는 1시간 캐시 단가($2.00)다(2026-09-16 정정, 공식 가격표 확인).
Haiku 4.5는 캐시 쓰기가 TTL별로 갈린다 — 5분 캐시는 $1.25, 1시간 캐시는 $2.00.
지금 캐시를 쓰는 호출은 services/llm.py의 classify_news()(2단계) 하나뿐이고
cache_control이 "ttl": "1h"로 고정돼 있어 상수 하나로 맞는다. 5분 캐시를 쓰는
호출이 새로 생기면 이 상수를 그 호출까지 함께 쓰는 단일 값으로 두면 안 되고,
호출별로 단가를 갈라야 한다.
"""

USD_KRW = 1400

PRICE_PER_MILLION_TOKENS_USD = {
    "input": 1.00,
    "output": 5.00,
    "cache_write": 2.00,
    "cache_read": 0.10,
}


def compute_cost_krw(input_tokens, output_tokens, cache_write_tokens, cache_read_tokens) -> int:
    """토큰 네 값으로 원화 비용을 계산해 반올림한 정수로 반환한다. 필드 이름은
    RunJob 기준이다 — cache_write_tokens는 cache_creation_input_tokens, cache_read_tokens는
    cache_read_input_tokens를 그대로 넘기면 된다(RunJob에 그런 이름의 필드는 없다)."""
    usd = (
        input_tokens / 1_000_000 * PRICE_PER_MILLION_TOKENS_USD["input"]
        + output_tokens / 1_000_000 * PRICE_PER_MILLION_TOKENS_USD["output"]
        + cache_write_tokens / 1_000_000 * PRICE_PER_MILLION_TOKENS_USD["cache_write"]
        + cache_read_tokens / 1_000_000 * PRICE_PER_MILLION_TOKENS_USD["cache_read"]
    )
    return round(usd * USD_KRW)
