from django.db import models
from apps.news.models import News


class Report(models.Model):
    STATUS_CHOICES = [
        ("generating", "생성중"),
        ("done", "완료"),
        ("failed", "실패"),
    ]

    year = models.IntegerField()
    week = models.IntegerField()
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
        ordering = ["-year", "-week"]
        unique_together = ("year", "week")

    def __str__(self):
        return f"{self.year}년 {self.week}주차 — {self.title}"


class ReportNews(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE)
    news = models.ForeignKey(News, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("report", "news")
