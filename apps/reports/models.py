import uuid

from django.db import models
from apps.news.models import News


class Report(models.Model):
    PERIOD_CHOICES = [
        ("daily", "일간"),
        ("weekly", "주간"),
        ("monthly", "월간"),
    ]
    STATUS_CHOICES = [
        ("generating", "생성중"),
        ("done", "완료"),
        ("failed", "실패"),
    ]

    uid = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    period_type = models.CharField(max_length=10, choices=PERIOD_CHOICES, default="weekly")
    date_from = models.DateField()
    date_to = models.DateField()
    title = models.CharField(max_length=500)
    overview = models.TextField(blank=True)
    content = models.TextField(blank=True)
    # 축약본 (2026-08-06, docs/planning.md "보고서 길이 버전"). 정본(content)은 작성·검사의
    # 기준이고, 이 필드는 정본에서 부연 문장만 삭제해 만든 표현이다 — 별도 문서가 아니라
    # 같은 보고서의 두 번째 표현이므로 title/overview/news는 공유하고 이 필드만 추가한다.
    # RA가 아직 채우지 않은 과거·신규 보고서는 빈 문자열로 남으며, display_content가 정본으로
    # 조용히 폴백한다(500 금지).
    content_short = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="generating")
    slack_sent_at = models.DateTimeField(null=True, blank=True)
    news = models.ManyToManyField(News, through="ReportNews", related_name="reports")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_from"]
        unique_together = ("period_type", "date_from")

    def __str__(self):
        return f"{self.get_period_type_display()} {self.date_from} — {self.title}"

    @property
    def display_content(self):
        """화면에 기본으로 보여줄 본문(축약본, 없으면 정본으로 폴백).

        docs/planning.md "보고서 길이 버전" 9번: 기본은 축약본이지만 비어 있을 수 있는
        과거/작성 중 보고서를 위해 조용히 정본으로 대체한다(500 금지). 버전 전환 UI 자체는
        PD 몫이라 이 프로퍼티는 그 UI가 기본으로 물어볼 값만 준비해 둔 것이다.
        """
        return self.content_short or self.content


class ReportNews(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE)
    news = models.ForeignKey(News, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("report", "news")
