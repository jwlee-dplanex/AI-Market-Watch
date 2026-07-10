from django.db import models
from apps.news.models import News


class DataSource(models.Model):
    SOURCE_TYPE_CHOICES = [
        ("api", "API"),
        ("rss", "RSS"),
        ("crawl", "크롤링"),
    ]

    name = models.CharField(max_length=100)
    url = models.URLField(max_length=2000)
    source_type = models.CharField(max_length=10, choices=SOURCE_TYPE_CHOICES)
    schedule = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Keyword(models.Model):
    TYPE_COLLECT = "수집"
    TYPE_EXCLUDE = "제외"
    TYPE_CHOICES = [
        (TYPE_COLLECT, "수집"),
        (TYPE_EXCLUDE, "제외"),
    ]

    SORT_DATE = "date"
    SORT_SIM  = "sim"
    SORT_CHOICES = [
        (SORT_DATE, "최신순"),
        (SORT_SIM,  "관련도순"),
    ]

    keyword      = models.CharField(max_length=100)
    keyword_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=TYPE_COLLECT)
    sort         = models.CharField(max_length=10, choices=SORT_CHOICES, default=SORT_DATE)
    is_active    = models.BooleanField(default=True)

    def __str__(self):
        return f"[{self.keyword_type}] {self.keyword}"


class Prompt(models.Model):
    name = models.CharField(max_length=100)
    purpose = models.CharField(max_length=200)
    content = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Schedule(models.Model):
    TYPE_CHOICES = [
        ("collect", "뉴스 수집"),
        ("report", "보고서 생성"),
    ]

    schedule_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    cron_expr = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.get_schedule_type_display()} ({self.cron_expr})"


class CollectionLog(models.Model):
    STATUS_CHOICES = [
        ("success", "성공"),
        ("fail", "실패"),
    ]

    source = models.ForeignKey(DataSource, on_delete=models.SET_NULL, null=True, related_name="logs")
    started_at = models.DateTimeField()
    collected_count = models.IntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.started_at:%Y-%m-%d %H:%M} — {self.status}"


class LLMLog(models.Model):
    STATUS_CHOICES = [
        ("success", "성공"),
        ("fail", "실패"),
    ]

    news = models.ForeignKey(News, on_delete=models.SET_NULL, null=True, blank=True, related_name="llm_logs")
    prompt_name = models.CharField(max_length=100)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.prompt_name} — {self.status}"


class SlackConfig(models.Model):
    channel_name = models.CharField(max_length=100)
    webhook_url = models.URLField(max_length=2000)
    is_active = models.BooleanField(default=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.channel_name


class Organization(models.Model):
    ORG_TYPE_CHOICES = [
        ("금융사", "금융사"),
        ("보험사", "보험사"),
        ("AI",    "AI"),
    ]

    name      = models.CharField(max_length=100, unique=True)
    org_type  = models.CharField(max_length=20, choices=ORG_TYPE_CHOICES)
    aliases   = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["org_type", "name"]

    def __str__(self):
        return f"[{self.org_type}] {self.name}"


class TechTopic(models.Model):
    """기술 관점 태그. Organization(기관 축)과 병존하는 두 번째 분류 축.
    org_type 같은 하위 유형 필드는 두지 않는 평면 큐레이션 어휘."""

    name      = models.CharField(max_length=100, unique=True)
    aliases   = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
