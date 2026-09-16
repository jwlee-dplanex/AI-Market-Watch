"""SET-006 「실행 이력과 비용」이 쓰는 LLM 비용 계산 (docs/design.md SET-006 1차 개정 절,
2026-09-16). 단가와 환율을 한 곳에 모아, 모델이나 환율이 바뀌면 이 파일 한 곳과
templates/setting/logs.html의 각주 문장만 같이 고치면 되게 한다.

🔴 Haiku 4.5 단가다(config/settings/base.py BEDROCK_MODEL_SMART가 지금 비용 때문에
Haiku를 가리키고 있는 것과 같은 맥락). Sonnet으로 되돌리면 이 단가도 함께 갱신해야 한다.
🔴 환율은 1,400원 고정이다(사용자 지시) — 실시간 환율 API를 붙이지 않는다.
"""

USD_KRW = 1400

PRICE_PER_MILLION_TOKENS_USD = {
    "input": 1.00,
    "output": 5.00,
    "cache_write": 1.25,
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
