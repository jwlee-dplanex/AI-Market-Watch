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


def normalize_org_pair(pk_a, pk_b):
    """기업 쌍(pk_a, pk_b)을 "작은 쪽 먼저"로 정규화하는 공유 규칙. OrgRelation.save()와
    apps/graph/views.py의 _get_edge_orgs_or_404가 이 함수를 공유해서, 정규화 로직이 여러 곳에
    독립 구현되며 어긋나는 것을 막는다(코드리뷰 지적 사항)."""
    return (pk_a, pk_b) if pk_a <= pk_b else (pk_b, pk_a)


class OrgRelation(models.Model):
    """지식그래프(GRAPH-001) 2단계 — 기업 쌍(엣지)의 관계 성격을 RA가 수동으로 기록하는 라벨.
    docs/planning.md "지식그래프 개선 로드맵" 2단계 확정 스키마 그대로. 엣지당 라벨은 정확히 1개
    (자유 텍스트, M2M 아님). LLM 자동 분류가 아니라 RA가 근거뉴스를 읽고 직접 판단해 채운다."""

    org_a = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="relations_as_a")
    org_b = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="relations_as_b")
    label = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    news = models.ManyToManyField(News, blank=True, related_name="org_relations")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("org_a", "org_b")

    def save(self, *args, **kwargs):
        # 정규화 규칙(org_a.pk < org_b.pk)을 모델 레벨에서도 강제한다. 저장 뷰가 이미
        # graph_edge_panel과 동일하게 normalize_org_pair()로 정규화해서 넘기지만, 다른 호출
        # 경로(예: 셸/관리자 화면)에서 순서를 뒤집어 넘겨도 (A,B)/(B,A) 중복 레코드가 생기지
        # 않도록 이중 방어한다.
        if self.org_a_id and self.org_b_id:
            self.org_a_id, self.org_b_id = normalize_org_pair(self.org_a_id, self.org_b_id)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.org_a} × {self.org_b}: {self.label}"
