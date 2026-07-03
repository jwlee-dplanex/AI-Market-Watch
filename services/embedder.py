import voyageai
from django.conf import settings
from apps.news.models import News, Embedding


_client = None


def _get_client() -> voyageai.Client:
    global _client
    if _client is None:
        _client = voyageai.Client(api_key=settings.VOYAGE_API_KEY)
    return _client


def embed_news(news: News) -> None:
    """단일 뉴스 임베딩 생성·저장 (수집 직후 또는 수동 호출용)"""
    text = f"{news.title}\n{news.body or ''}"
    if not text.strip():
        return
    result = _get_client().embed([text], model=settings.EMBEDDING_MODEL)
    Embedding.objects.update_or_create(
        news=news,
        defaults={
            "vector": result.embeddings[0],
            "model": settings.EMBEDDING_MODEL,
        },
    )


def embed_missing(batch_size: int = 128) -> dict:
    """임베딩 없는 뉴스 전체 일괄 처리"""
    qs = list(
        News.objects.filter(embedding__isnull=True).exclude(body="").order_by("-published_at")
    )
    total = len(qs)
    processed = 0
    batch_errors = 0

    for i in range(0, total, batch_size):
        batch = qs[i : i + batch_size]
        texts = [f"{n.title}\n{n.body}" for n in batch]
        try:
            result = _get_client().embed(texts, model=settings.EMBEDDING_MODEL)
            Embedding.objects.bulk_create(
                [
                    Embedding(news=n, vector=v, model=settings.EMBEDDING_MODEL)
                    for n, v in zip(batch, result.embeddings)
                ],
                ignore_conflicts=True,
            )
            processed += len(batch)
        except Exception:
            batch_errors += 1

    return {"total": total, "processed": processed, "batch_errors": batch_errors}
