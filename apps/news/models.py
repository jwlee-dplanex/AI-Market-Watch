import uuid

from django.db import models
from pgvector.django import VectorField


class News(models.Model):
    SOURCE_CHOICES = [
        ("naver_news", "네이버 뉴스"),
        ("opendart", "OpenDART"),
        ("rss", "RSS"),
    ]
    CATEGORY_CHOICES = [
        ("기술흐름", "기술 흐름"),
        ("기업사례", "기업 사례"),
        ("금융권활용", "금융권 활용"),
        ("규제·정책", "규제·정책"),
        ("경쟁사동향", "경쟁사 동향"),
    ]

    uid = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=2000)
    url_hash = models.CharField(max_length=64, unique=True, db_index=True)
    body = models.TextField(blank=True)
    image_url = models.URLField(max_length=2000, null=True, blank=True)
    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, blank=True)
    tags = models.JSONField(default=dict)
    summary = models.TextField(null=True, blank=True)
    is_processed = models.BooleanField(default=False)
    published_at = models.DateTimeField()
    collected_at = models.DateTimeField(auto_now_add=True)
    organizations = models.ManyToManyField(
        "setting.Organization",
        blank=True,
        related_name="news",
    )

    class Meta:
        ordering = ["-published_at"]

    def __str__(self):
        return self.title


class Embedding(models.Model):
    news = models.OneToOneField(News, on_delete=models.CASCADE, related_name="embedding")
    vector = VectorField(dimensions=1024)
    model = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Embedding({self.news_id})"


class IssueGroup(models.Model):
    title = models.CharField(max_length=500, null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    news = models.ManyToManyField(News, through="IssueGroupNews", related_name="issue_groups")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"IssueGroup({self.pk})"


class IssueGroupNews(models.Model):
    issue_group = models.ForeignKey(IssueGroup, on_delete=models.CASCADE)
    news = models.ForeignKey(News, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("issue_group", "news")


class Insight(models.Model):
    issue_group = models.ForeignKey(IssueGroup, on_delete=models.CASCADE, related_name="insights")
    content = models.TextField()
    implication = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Insight({self.issue_group_id})"
