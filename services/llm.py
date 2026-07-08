import json

import anthropic
from django.conf import settings

from apps.news.models import News
from apps.setting.models import LLMLog, Prompt

PROMPT_NAME = "뉴스 요약"
BODY_CHAR_LIMIT = 6000

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def _get_prompt_template() -> str:
    prompt = Prompt.objects.filter(name=PROMPT_NAME).first()
    if not prompt:
        raise RuntimeError(f"Prompt '{PROMPT_NAME}'이 설정되어 있지 않습니다.")
    return prompt.content


def classify_news(news: News) -> dict:
    """뉴스 1건의 관련성·요약을 Claude Haiku로 판단. 실패 시 예외 발생."""
    template = _get_prompt_template()
    body = (news.body or "")[:BODY_CHAR_LIMIT]
    # 프롬프트에 JSON 예시가 포함돼 있어 str.format()은 중괄호 충돌로 깨짐 → 단순 치환 사용
    prompt = template.replace("{title}", news.title).replace("{body}", body)

    response = _get_client().messages.create(
        model=settings.ANTHROPIC_MODEL_FAST,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = response.content[0].text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`").removeprefix("json").strip()

    try:
        result = json.loads(raw_text)
        is_relevant = bool(result["is_relevant"])
        summary = result.get("summary") or ""
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        LLMLog.objects.create(
            news=news, prompt_name=PROMPT_NAME, status="fail",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            error_message=f"JSON 파싱 실패: {e} / 응답: {raw_text[:500]}",
        )
        raise

    LLMLog.objects.create(
        news=news, prompt_name=PROMPT_NAME, status="success",
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    return {"is_relevant": is_relevant, "summary": summary}


def process_unclassified(limit: int | None = None) -> dict:
    """is_processed=False인 뉴스를 순회하며 관련성 판단 + 요약을 채운다."""
    qs = News.objects.filter(is_processed=False).order_by("-published_at")
    if limit:
        qs = qs[:limit]
    targets = list(qs)

    stats = {"total": len(targets), "processed": 0, "relevant": 0, "irrelevant": 0, "errors": 0}

    for news in targets:
        try:
            result = classify_news(news)
        except Exception:
            stats["errors"] += 1
            continue

        news.is_relevant = result["is_relevant"]
        news.summary = result["summary"]
        news.is_processed = True
        news.save(update_fields=["is_relevant", "summary", "is_processed"])

        stats["processed"] += 1
        stats["relevant" if result["is_relevant"] else "irrelevant"] += 1

    return stats
