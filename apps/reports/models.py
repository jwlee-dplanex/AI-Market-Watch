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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="generating")
    slack_sent_at = models.DateTimeField(null=True, blank=True)
    news = models.ManyToManyField(News, through="ReportNews", related_name="reports")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_from"]
        unique_together = ("period_type", "date_from")

    def __str__(self):
        return f"{self.get_period_type_display()} {self.date_from} — {self.title}"


class ReportNews(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE)
    news = models.ForeignKey(News, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("report", "news")
