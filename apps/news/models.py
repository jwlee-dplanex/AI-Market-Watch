import uuid

from django.db import models
from pgvector.django import VectorField


class NewsQuerySet(models.QuerySet):
    def verified(self):
        """검증 게이트(docs/planning.md "검증 게이트: 미검증 뉴스는 화면에 노출하지 않는다")
        통과분만 반환한다. RA가 처리 흐름 1번(노이즈 판정·삭제 + 태깅 검증·교정)을 마치고
        일괄 STATUS_VERIFIED로 전환한 뉴스만 여기 해당한다.

        (A) 직접 조회 경로(ALL-001 핵심 지표·최신 뉴스, NEWS-001 목록, NEWS-002 상세,
        GRAPH-001 노드·엣지·양쪽 패널)는 반드시 이 메서드를 거쳐야 한다.

        (B) 다음 세 경로는 정책상 의도적으로 이 메서드를 쓰지 않는다 — 명시 연결 M2M에
        게이트를 이중으로 걸면 상태가 어긋나는 순간 보고서·인사이트의 근거가 조용히
        사라지기 때문이다(출처 추적 가능성 최우선 원칙):
          - `Insight.news` / `Report.news` / `OrgRelation.news`
          - `apps/reports/templatetags/report_extras.py`의 `참고: <uid>` 해석 경로
          - `apps/dashboard/context_processors.py`의 사이드바 "마지막 수집" 표시
            (수집 파이프라인 생존 신호이지 뉴스 노출이 아니므로 예외)
        """
        return self.filter(status=News.STATUS_VERIFIED)


class News(models.Model):
    # 검증 게이트 상태 — 2단계만 둔다("보류" 없음, docs/planning.md 근거 참고).
    # ⚠️ default는 반드시 STATUS_UNVERIFIED여야 한다. 검증됨을 기본값으로 두면 신규
    # 수집분이 자동으로 게이트를 통과해 이 정책 전체가 무력화된다.
    STATUS_UNVERIFIED = "미검증"
    STATUS_VERIFIED = "검증됨"
    STATUS_CHOICES = [
        (STATUS_UNVERIFIED, "미검증"),
        (STATUS_VERIFIED, "검증됨"),
    ]

    uid = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=2000)
    url_hash = models.CharField(max_length=64, unique=True, db_index=True)
    body = models.TextField(blank=True)
    image_url = models.URLField(max_length=2000, null=True, blank=True)
    source_type = models.CharField(max_length=20)
    published_at = models.DateTimeField()
    collected_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_UNVERIFIED, db_index=True,
    )
    # RA가 배치를 검증됨으로 전환한 시각. 기존 레코드는 백필하지 않는다(모르는 값을
    # 지어내지 않는 원칙, docs/planning.md 3번) — 그래서 null 허용.
    verified_at = models.DateTimeField(null=True, blank=True)
    organizations = models.ManyToManyField(
        "setting.Organization",
        blank=True,
        related_name="news",
    )
    tech_topics = models.ManyToManyField(
        "setting.TechTopic",
        blank=True,
        related_name="news",
    )

    objects = NewsQuerySet.as_manager()

    @property
    def is_verified(self):
        """템플릿에서 게이트 통과 여부를 물을 때 쓴다. 상태 문자열('검증됨')을 템플릿에
        하드코딩하면 나중에 값이 바뀔 때 조용히 깨지므로, 비교는 항상 여기로 모은다."""
        return self.status == self.STATUS_VERIFIED

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
