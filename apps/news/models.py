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


class DeletedNewsRecord(models.Model):
    """docs/planning.md "판정 기록 보존 정책: 버린 것도 자산이다" (2026-08-04 확정) 구현.

    RA/사용자가 뉴스를 삭제할 때 `delete_news_with_record()`(apps/news/services.py)를 거쳐
    함께 남기는 판정 기록. `ExcludedURL`(재수집 차단 핫패스, 스키마 동결 대상)과는 완전히
    별개 모델이며 `url_hash`로만 느슨하게 연결한다 — FK가 아니고 unique도 아니다. 같은
    URL이 재수집·재판정되면 이 모델에는 여러 건이 쌓일 수 있는 "이력"이기 때문이다
    (`ExcludedURL.url_hash`는 존재 여부만 의미 있는 unique 인덱스라 성격이 다르다).

    ⚠️ 비노출 계약(정책 6번): 어떤 뷰·컨텍스트 프로세서·집계에서도 이 모델을 조회하지
    않는다. Django admin에도 등록하지 않는다. 검증 게이트보다 강한 "영구 비노출"이며,
    유일한 소비자는 사람(RA·PE)과 향후 옵션 B 코드화 작업이다.
    """

    # 판정 주체 — 권장 어휘(고정 강제 아님. 아래 4개 상수 우선 사용을 권장한다).
    JUDGED_BY_RA = "RA"
    JUDGED_BY_USER = "사용자(화면 삭제)"
    JUDGED_BY_RETRO = "소급 정비"
    JUDGED_BY_AUTO = "자동 판정"

    # --- 기사 식별·원문 (삭제 시점 News 필드를 그대로 복사) ---
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=2000)
    # ExcludedURL과 달리 unique 제약을 걸지 않는다 — 이력이라 같은 url_hash가 여러 건일 수 있다.
    url_hash = models.CharField(max_length=64, db_index=True)
    body = models.TextField(
        blank=True,
        help_text="수집 시점 크롤링본 그대로. 요약·가공하지 않는다. 외부 공개·재발행 금지"
                   "(내부 판별 로직 개발 재료 용도로 한정).",
    )
    source_type = models.CharField(max_length=20)
    published_at = models.DateTimeField()
    collected_at = models.DateTimeField()

    # --- 판정 근거 2종 (이 정책의 핵심) ---
    criterion_code = models.CharField(
        max_length=20,
        blank=True,
        help_text=(
            "권장 어휘(고정 choices 아님 — docs/planning.md '판정 기록 보존 정책' 1번 근거: "
            "관련성 판단 기준이 계속 개정되므로 enum으로 박지 않는다): "
            "1-a(배경 언급) / 1-b(부차 요소) / 2(중복 보도) / 3(키워드 오탐) / "
            "4(증시 브리핑) / 5(AI 단독, 금융 연결 없음) / S-KLS(임시 스코프 제외) / 기타"
        ),
    )
    reason = models.TextField(blank=True, help_text="삭제 사유 1~2문장 자유 서술")

    judged_by = models.CharField(
        max_length=30,
        default=JUDGED_BY_RA,
        help_text=f"권장 어휘: {JUDGED_BY_RA} / {JUDGED_BY_USER} / {JUDGED_BY_RETRO} / {JUDGED_BY_AUTO}",
    )

    # --- 삭제 시점 태그 스냅샷 ---
    # M2M은 news.delete()와 함께 사라지므로, 이름 목록을 여기 복사해 둬야 남는다.
    # collector 과다태깅 실패 사례가 삭제분에 몰려 있어 옵션 B 핵심주체 판별의 직접 재료.
    organizations_snapshot = models.JSONField(
        default=list, blank=True, help_text="삭제 시점 연결돼 있던 Organization.name 목록",
    )
    tech_topics_snapshot = models.JSONField(
        default=list, blank=True, help_text="삭제 시점 연결돼 있던 TechTopic.name 목록",
    )

    judged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-judged_at"]

    def __str__(self):
        return f"DeletedNewsRecord({self.title!r}, {self.criterion_code or '기타'})"


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
