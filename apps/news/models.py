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
    # 2026-08-06 도입(PM P1). 수집 시 Naver API 호출에 쓴 Keyword.keyword 문자열 목록(당시
    # 표기 그대로) — 사후 재매칭이 아니라 "그 키워드로 검색해서 들어왔다"는 실측 사실이다.
    # FK가 아니라 문자열인 이유는 organizations_snapshot과 동일: Keyword가 나중에 수정·
    # 비활성화돼도 수집 당시 어떤 키워드였는지가 그대로 남아야 한다. 한 기사가 여러 키워드에
    # 걸리는 경우가 흔해(2026-08-06 실측 21건, 4개 이상도 4건) 전부 담는다 — 최초 1건만
    # 남기면 그 분석을 다시 할 수 없다.
    # ⚠️ 이 필드 도입 이전(2026-08-06 이전) 수집분은 소급 채움 없이 빈 리스트로 남는다 —
    # 재매칭으로 채우면 실측과 근사가 한 필드에 섞여 나중에 구분할 수 없어진다.
    matched_keywords = models.JSONField(
        default=list, blank=True,
        help_text="수집 시 매칭된 Keyword.keyword 문자열 목록. 2026-08-06 이전 수집분은 "
                   "이 필드 도입 전이라 빈 리스트(소급 채움 없음).",
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
    # 2026-08-06 도입(PM P1) — News.matched_keywords를 삭제 시점 그대로 복사한 스냅샷.
    # "오늘 필요했던 건 살아남은 쪽이 아니라 버려진 쪽"(PM)이라 DeletedNewsRecord에도
    # 반드시 함께 남긴다. 이 필드 도입 이전 삭제 이력은 소급 채움 없이 빈 리스트.
    matched_keywords_snapshot = models.JSONField(
        default=list, blank=True,
        help_text="삭제 시점 News.matched_keywords 그대로. 2026-08-06 이전 삭제 이력은 "
                   "이 필드 도입 전이라 빈 리스트(소급 채움 없음).",
    )

    judged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-judged_at"]

    def __str__(self):
        return f"DeletedNewsRecord({self.title!r}, {self.criterion_code or '기타'})"


class TagCorrectionRecord(models.Model):
    """docs/planning.md "판정 기록 보존 정책: 버린 것도 자산이다" 4번(P1) 구현.

    RA가 배치를 처리하며 collector 과다태깅(핵심 주체 vs 배경 언급을 구분하지 못하는
    구조적 한계)을 손으로 교정할 때 그 차분을 남긴다. `DeletedNewsRecord`와 역할이
    다르다 — 그건 "삭제된 뉴스가 삭제 시점에 갖고 있던 태그 스냅샷"이고, 이건 "살아남은
    뉴스에서 사람이 손으로 고친 내역"이다. 대상 뉴스는 삭제되지 않고 DB에 남으므로
    "현재 태그"는 `News.organizations`/`News.tech_topics`로 언제든 조회 가능하다 —
    이 모델이 붙잡아 두는 건 그래서 사라지는 "뗀/붙인 태그"라는 차분 자체다.

    `correct_news_tag()`(apps/news/services.py)를 거쳐서만 생성한다.
    `news.organizations.add()/remove()`를 직접 호출하지 않는다.

    ⚠️ 비노출 계약: `DeletedNewsRecord`와 동일 — 어떤 뷰·컨텍스트 프로세서·집계에서도
    조회하지 않는다. Django admin에도 등록하지 않는다. 유일한 소비자는 사람(RA·PE)과
    향후 옵션 B 코드화 작업("핵심 주체 vs 배경 언급" 판별 로직의 명세 재료).
    """

    AXIS_ORGANIZATION = "organization"
    AXIS_TECH_TOPIC = "tech_topic"
    AXIS_CHOICES = [
        (AXIS_ORGANIZATION, "기업"),
        (AXIS_TECH_TOPIC, "기술 주제"),
    ]

    ACTION_ADD = "add"
    ACTION_REMOVE = "remove"
    ACTION_CHOICES = [
        (ACTION_ADD, "추가"),
        (ACTION_REMOVE, "제거"),
    ]

    # 판정 주체 어휘는 DeletedNewsRecord와 동일 개념이라 값을 그대로 참조한다(드리프트 방지).
    JUDGED_BY_RA = DeletedNewsRecord.JUDGED_BY_RA
    JUDGED_BY_USER = DeletedNewsRecord.JUDGED_BY_USER
    JUDGED_BY_RETRO = DeletedNewsRecord.JUDGED_BY_RETRO
    JUDGED_BY_AUTO = DeletedNewsRecord.JUDGED_BY_AUTO

    news = models.ForeignKey(News, on_delete=models.CASCADE, related_name="tag_corrections")
    axis = models.CharField(max_length=20, choices=AXIS_CHOICES)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    # FK가 아니라 이름 문자열 — DeletedNewsRecord의 태그 스냅샷(organizations_snapshot 등)과
    # 같은 이유. 대상(Organization/TechTopic)이 나중에 개명·비활성화돼도 교정 당시 기록은
    # 그대로 남아야 한다.
    target_name = models.CharField(max_length=200)
    reason = models.TextField(blank=True, help_text="교정 사유, 짧게(1문장 권장)")
    judged_by = models.CharField(
        max_length=30,
        default=JUDGED_BY_RA,
        help_text=f"권장 어휘: {JUDGED_BY_RA} / {JUDGED_BY_USER} / {JUDGED_BY_RETRO} / {JUDGED_BY_AUTO}",
    )
    corrected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-corrected_at"]

    def __str__(self):
        return f"TagCorrectionRecord(news={self.news_id}, {self.action} {self.target_name!r})"


class Embedding(models.Model):
    news = models.OneToOneField(News, on_delete=models.CASCADE, related_name="embedding")
    vector = VectorField(dimensions=1024)
    model = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Embedding({self.news_id})"


class Insight(models.Model):
    # 승격 위계 등급(1급/2급/3급) — docs/planning.md "승격 위계 등급(1급/2급/3급)을
    # Insight에 저장한다"(2026-08-06 확정). 목적은 등급을 매기는 것 자체가 아니라 1급이
    # 실제 몇 건인지 관측하는 것과 RA 판단(헤드라이너 지정 등)의 입력이다.
    # ⚠️ 화면은 이 값을 표시하지도, 이 값으로 화면 내용을 고르지도 않는다(정책 2번) —
    # 등급이 화면 내용을 바꾸면 제품 데이터, 안 바꾸면 내부 도구라는 것이 판별선이다.
    # 조회는 SET 화면군(예약만, 미설계) / 배치 보고서 / ORM에서만 한다.
    GRADE_UNSPECIFIED = "unspecified"
    GRADE_1 = "1"
    GRADE_2 = "2"
    GRADE_3 = "3"
    GRADE_CHOICES = [
        (GRADE_UNSPECIFIED, "미지정"),
        (GRADE_1, "1급"),
        (GRADE_2, "2급"),
        (GRADE_3, "3급"),
    ]

    title = models.CharField(max_length=500)
    news = models.ManyToManyField(News, through="InsightNews", related_name="insights")
    content = models.TextField()
    implication = models.TextField()
    # ⚠️ default는 반드시 GRADE_UNSPECIFIED여야 한다. 3급을 기본값으로 두면 도입 직후
    # 집계가 "3급 34건"으로 나와 관측이 아니라 기본값을 세는 꼴이 되고, 이 필드를 만든
    # 유일한 이유(미지정과 판정된 3급의 구분, 정책 1번)가 사라진다.
    # 사유 필드·이력 테이블은 두지 않는다(정책 4번) — 변경은 덮어쓰기, 변경 사실은 배치
    # 보고서(research/batches/YYYY-MM-DD.md)에 남긴다. Insight 삭제·병합과 함께 이력이
    # 사라지는 TagCorrectionRecord류 실패를 반복하지 않기 위함이다.
    grade = models.CharField(
        max_length=20, choices=GRADE_CHOICES, default=GRADE_UNSPECIFIED, db_index=True,
    )
    # 대시보드 헤드라이너(docs/planning.md "대시보드 헤드라이너" 2026-08-06 신설) — "헤드라이너
    # 여부 + 그 안에서의 순서"를 값 하나로 담는다(정책 7번, 불리언 하나로는 부족하다는 것이
    # 명시 근거). null = 헤드라이너 아님(기본값). 1 이상 정수 = 헤드라이너이며 그 표시 순서
    # (1번이 가장 중요). 상한 3건은 DB 제약으로 강제하지 않는다 — RA가 실수로 4건 이상
    # 지정해도 화면이 상위 3건까지만 렌더하는 안전장치로 충분하다(정책 2번).
    # 배치마다 전량 교체(자동 만료, 정책 6번)이므로 별도 만료 시각 필드는 두지 않는다.
    headliner_order = models.PositiveSmallIntegerField(null=True, blank=True, default=None)
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
