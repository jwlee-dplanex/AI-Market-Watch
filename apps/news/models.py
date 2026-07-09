import uuid

from django.db import models
from pgvector.django import VectorField


class News(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=2000)
    url_hash = models.CharField(max_length=64, unique=True, db_index=True)
    body = models.TextField(blank=True)
    image_url = models.URLField(max_length=2000, null=True, blank=True)
    source_type = models.CharField(max_length=20)
    published_at = models.DateTimeField()
    collected_at = models.DateTimeField(auto_now_add=True)
    organizations = models.ManyToManyField(
        "setting.Organization",
        blank=True,
        related_name="news",
    )

    class Meta:
        ordering = ["-published_at", "-pk"]

    def __str__(self):
        return self.title


class ExcludedURL(models.Model):
    """사용자가 삭제한 뉴스의 URL 해시. 재수집 시 다시 추가되지 않도록 차단하는 용도."""
    url_hash = models.CharField(max_length=64, unique=True, db_index=True)
    deleted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.url_hash


class Embedding(models.Model):
    news = models.OneToOneField(News, on_delete=models.CASCADE, related_name="embedding")
    vector = VectorField(dimensions=1024)
    model = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Embedding({self.news_id})"


class Insight(models.Model):
    title = models.CharField(max_length=500)
    news = models.ManyToManyField(News, through="InsightNews", related_name="insights")
    content = models.TextField()
    implication = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class InsightNews(models.Model):
    insight = models.ForeignKey(Insight, on_delete=models.CASCADE)
    news = models.ForeignKey(News, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("insight", "news")
