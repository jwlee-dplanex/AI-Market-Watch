import uuid
from urllib.parse import urlparse

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

        🔴 (D) 네 번째 예외(2026-09-04 신설) — SET-010 검토 화면(`setting/run/review/<작업>/`)의
        확정 대기 목록에 한해 미검증 `News`를 보여준다. 범위는 **SET-010과 그 하위 검토
        화면으로만** 한정된다(docs/planning.md "검증 게이트" 2-(D)가 정본). 이 메서드에
        게이트를 끄는 옵션 인자를 뚫지 않는다 — 그 화면은 `apps/setting/views.py`에서
        미검증만 뽑는 별도 이름 있는 조회를 따로 쓴다. NEWS-002는 미검증이면 여전히
        404이며, ALL-001·NEWS-001·GRAPH-001의 어떤 숫자에도 이 예외로 노출된 뉴스가
        섞이지 않는다.

        🔴 (E) 다섯 번째 조건(2026-09-17, 사용자 제안 "`NewsroomArticle.duplicate_of`와
        같게 구현" · docs/planning.md 4-A) — `duplicate_of`가 채워진 News(대표가 아니라
        같은 사건의 나머지)는 status와 무관하게 함께 제외한다. **행은 지우지 않는다.**
        형태는 `NewsroomArticleQuerySet.for_newsroom_display()`(`apps/newsroom/models.py:242`,
        `duplicate_of__isnull=True`)와 같지만 근거는 다르므로 갈라 적는다:
          - 교보(뉴스룸) 축이 지우지 않는 이유 — 재수집 차단 장치(`ExcludedURL` 대응물)가
            없어 지우면 다시 들어오고, 뉴스룸엔 사람 삭제 기능 자체가 없다(정책 9번 ⑧).
            이 근거는 조사 축에 해당하지 않는다 — 조사 축에는 `ExcludedURL`이 있다.
          - 🔴 조사 축이 지우지 않는 이유 — 위 (B)의 삭제 금지 셋에 걸리면 대표 외
            나머지를 지울 수 없다. 실측(2026-09-17): 그날 수집분 23건 전수가 이미
            `Insight`에 연결돼 있어 "대표만 남기고 나머지를 삭제"가 산술적으로
            공집합이었다 — 삭제 기반 설계 자체가 이미 성립하지 않는다.
          같은 결론(행을 지우지 않는다)이지만 근거가 다르므로, 한쪽이 나중에 무너져도
          (예: 뉴스룸에 삭제 기능이 생기거나, 조사 축의 삭제 금지 셋이 바뀌더라도)
          다른 쪽은 흔들리지 않는다.

        ⚠️ 대표는 절대 `duplicate_of`가 채워지지 않는다(자기 자신을 가리키지 않음,
        교보 축과 동일 계약) — 지식그래프 엣지 임계(라벨 AND 기간 내 검증 뉴스
        공동언급 ≥ 1건)가 이 성질에 기대어 "묶음마다 대표 1건은 반드시 남으므로
        공동언급이 0으로 떨어지는 경로가 없다"를 보장한다.

        (B)의 예외 셋(`Insight.news`/`Report.news`/`OrgRelation.news`, `report_extras`의
        `참고: <uid>` 해석 경로)은 이 (E) 조건도 함께 우회한다 — `verified()`를 거치지
        않으므로 감춘 기사도 시사점·보고서·관계의 근거 목록에서는 그대로 보인다.
        """
        return self.filter(status=News.STATUS_VERIFIED, duplicate_of__isnull=True)


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
    # 🔴 3단계(주요 이슈) 탈락 표식(docs/planning.md "SET-010 검토 단위" 절 11번,
    # 2026-09-16). 3단계 확정에서 이슈로 묶이지 않은 후보(RunJob.insight_candidates에는
    # 있었지만 어떤 Insight.news에도 속하지 않은 News)에 붙는다. 표식이 있으면 다음
    # 3단계 실행 대상에서 빠진다 — 값을 지우면(관리 명령) 다시 대상이 된다. 승격
    # 기준이 통과/탈락 이분법이라 탈락분은 재실행마다 같은 이유로 다시 탈락하므로,
    # 표식이 없으면 3단계가 "미배정 전체"를 대상으로 삼는 순간 영구히 할 일이 남는다.
    insight_dismissed_at = models.DateTimeField(null=True, blank=True)
    # 🔴 2026-09-16 23차 개정(docs/planning.md 「SET-010 검토 단위」 9번, design.md 23차
    # 개정 ②) — 2단계(cleanup) 관련성 판정 시도가 제안 없이 끝난 누적 횟수. SDK 내부
    # 재시도는 한 번으로 센다(services/runner.py의 classify_news() 호출 실패 1건 =
    # +1). 이 값이 3 이상이면서 아직 미검증인 News를 SET-010 화면이 "반복 실패
    # 자료"로 지목한다 — B(미판정)가 0이 되어야 검토가 열리는데 같은 자료가 계속
    # 실패하면 B가 영영 안 줄기 때문이다. 별도 모델 대신 News에 칸 하나를 더한
    # 이유는 이 값이 오직 "그 News가 몇 번 실패했나"만 답하면 되고(집계·이력 조회가
    # 필요 없다), 별도 테이블은 조인 하나를 더할 뿐 실익이 없기 때문이다.
    classify_fail_count = models.IntegerField(default=0)
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
    # 🔴 2026-09-17 신설(사용자 제안 "NewsroomArticle.duplicate_of와 같게 구현" ·
    # docs/planning.md 4-A) — self-FK로 "같은 사건의 대표가 무엇인가" 하나의 질문에
    # 묶음을 담는다. `NewsroomArticle.duplicate_of`(apps/newsroom/models.py:382)와
    # 정확히 같은 형태다. 대표 기사 자신은 반드시 None이다(자기 자신을 가리키지
    # 않음) — NewsQuerySet.verified() (E)가 이 계약에 기대어 지식그래프 엣지
    # 임계(공동언급 ≥ 1건)를 지킨다.
    #
    # 게이트는 NewsQuerySet.verified()에 조건 한 줄(duplicate_of__isnull=True)로만
    # 건다 — 새 게이트를 세우지 않는다. 이 필드로 감춘 News는 삭제하지 않는다:
    # Insight.news/Report.news/OrgRelation.news(삭제 금지 셋)가 걸려 있으면 애초에
    # 삭제할 수 없기 때문이다(실측: 2026-09-17 수집분 23건 전수가 Insight에 연결돼
    # 있어 삭제 기반 설계가 성립하지 않았다) — 교보 축(재수집 차단 장치 부재·삭제
    # 기능 부재)과는 근거가 다르다.
    #
    # on_delete=SET_NULL — 교보 축과 같은 선택이되 근거는 조사 축에 맞게 다시
    # 확인했다: 대표 News가 (아직 명시 연결이 붙기 전에) 삭제되더라도 그 대표를
    # 가리키던 나머지들까지 함께 사라지면 "행을 지우지 않는다"는 이 필드의 존재
    # 이유가 깨진다. SET_NULL이면 대표를 잃은 나머지는 duplicate_of가 비면서
    # verified()에 다시 드러나 독립 기사로 남는다 — CASCADE였다면 조용히 함께
    # 삭제됐을 것이다.
    duplicate_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="duplicates",
        help_text="같은 사건을 다루는 대표 News. 대표 기사 자신은 None이다. status는 "
                   "두 기사 모두 그대로 둔다 — 이 필드로만 묶고 삭제하지 않는다.",
    )

    objects = NewsQuerySet.as_manager()

    @property
    def is_verified(self):
        """템플릿에서 게이트 통과 여부를 물을 때 쓴다. 상태 문자열('검증됨')을 템플릿에
        하드코딩하면 나중에 값이 바뀔 때 조용히 깨지므로, 비교는 항상 여기로 모은다."""
        return self.status == self.STATUS_VERIFIED

    @property
    def is_duplicate(self):
        """이 News가 대표가 아니라 같은 사건의 나머지(duplicate_of가 채워짐)인지.
        is_verified와 같은 이유로 둔다 — 템플릿이 `news.duplicate_of`를 직접 None
        비교하는 대신 이 프로퍼티로 물어보게 한다(2026-09-17, NEWS-002 상세 게이트
        수정: 미검증은 여전히 404지만 중복은 검증된 근거이므로 상세를 열어 준다)."""
        return self.duplicate_of_id is not None

    @property
    def source_domain(self):
        """목록 카드에 쓸 출처. 이 프로젝트 어디에도 언론사명을 추출하는 인프라가 없어
        매체명을 지어내는 대신 URL 도메인을 그대로 보여준다 — 실측 가능한 값만 쓴다는
        원칙(「무조건 팩트 기반」)을 지키는 최소 구현이다.

        ⚠️ source_type과 다르다. source_type은 어느 경로로 수집했는지(naver 등)이지
        어느 매체가 발행했는지가 아니다. 둘을 섞어 쓰면 화면이 거짓을 말한다.

        NewsroomArticle.source_domain과 같은 구현이다. 두 모델이 서로를 import하지
        않게 각자 두었다 — 뉴스룸을 News에서 분리한 이유와 같다."""
        try:
            netloc = urlparse(self.url).netloc
            return netloc[4:] if netloc.startswith("www.") else netloc
        except ValueError:
            return ""

    class Meta:
        ordering = ["-published_at", "-pk"]
        indexes = [
            # 🔴 2026-09-17 PE 신설(점검 지적 ⑤ — published_at 인덱스 0개).
            # 비교 창(중복 판별)·기간 필터(대시보드·지식그래프)·
            # insights_in_period()의 Min/Max·최신순 정렬(Meta.ordering 그대로)·
            # _adjacent_news()가 전부 이 필드를 건다. 지금(News 수백 건)은
            # Postgres가 어차피 Seq Scan을 고를 규모라 체감 차이는 없지만,
            # 테이블이 작을 때 AddIndex는 사실상 즉시 끝나(락 시간 무시할
            # 수준) CONCURRENTLY가 필요 없다 — 나중에 행이 많아진 뒤 만들면
            # 그때는 필요해진다.
            models.Index(fields=["published_at"], name="news_published_at_idx"),
            # 🔴 2026-09-17 PE 신설(점검 지적 ⑤ 복합 인덱스 판단) — NewsQuerySet.
            # verified()가 이 두 조건(status, duplicate_of_id IS NULL)을 항상
            # 함께 건다. verified()는 앱 전체에서 News를 직접 읽는 거의 모든
            # 경로의 게이트라 가장 자주 실행되는 쿼리 형태다. status가 먼저
            # 오는 이유 — duplicate_of_id IS NULL은 선택도가 낮다(대다수
            # News가 중복이 아니라 NULL이라 이 조건 하나로는 거의 안 좁혀진다).
            # status를 선행 컬럼으로 두면 그 값으로 먼저 좁힌 뒤 남은 행에서
            # duplicate_of_id를 걸러 인덱스 단계에서 조건이 거의 다 끝난다.
            # 기존 duplicate_of FK 인덱스(status 없이 duplicate_of_id 단독)는
            # 그대로 둔다 — `News.duplicates`(같은 대표를 가리키는 나머지 조회)
            # 등 status 없이 duplicate_of_id만 거는 경로가 있어 지우면 그
            # 경로가 손해를 본다.
            models.Index(fields=["status", "duplicate_of"], name="news_status_dup_idx"),
        ]

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

    # 판정 주체 — 권장 어휘(고정 강제 아님. 아래 5개 상수 우선 사용을 권장한다).
    JUDGED_BY_RA = "RA"
    JUDGED_BY_USER = "사용자(화면 삭제)"
    JUDGED_BY_RETRO = "소급 정비"
    JUDGED_BY_AUTO = "자동 판정"
    # 🔴 2026-09-16 PE 신설(docs/planning.md "2단계 비용 절감 정책" 4-3번) — 조사
    # 2단계 사전 차단 규칙(services/cleanup_prefilter.py)이 LLM 없이 코드로 직접
    # 내린 삭제 판정. `자동 판정`(LLM, classify_news())과 통계를 섞지 않으려고
    # 별도 값을 둔다 — 규칙 정확도와 LLM 정확도는 다른 질문이다. 표기는
    # apps/newsroom/models.py의 JUDGED_BY_CODE_TITLE_RULE("코드(제목 규칙)")과
    # 같은 형태를 따른다.
    JUDGED_BY_CODE_AI_KEYWORD_RULE = "코드(AI 낱말 규칙)"

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
            "4(증시 브리핑) / 5(AI 단독, 금융 연결 없음) / 6(묶음, 단신 브리핑 기사) / "
            "S-KLS(임시 스코프 제외) / 기타"
        ),
    )
    reason = models.TextField(blank=True, help_text="삭제 사유 1~2문장 자유 서술")

    judged_by = models.CharField(
        max_length=30,
        default=JUDGED_BY_RA,
        help_text=(
            f"권장 어휘: {JUDGED_BY_RA} / {JUDGED_BY_USER} / {JUDGED_BY_RETRO} / "
            f"{JUDGED_BY_AUTO} / {JUDGED_BY_CODE_AI_KEYWORD_RULE}"
        ),
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
    # ⚠️ 축이 2026-08-07에 바뀌었다. 종전 축은 "거래 유형"(계약·투자가 있으면 1급)이었고
    # 새 축은 "경영 효과"다 — 1급은 그 회사의 업무·상품이 실제로 바뀌었고 이미 가동 중인 건,
    # 2급은 바꾸려는 움직임(계약·투자·조직 신설)은 있으나 아직 안 바뀐 건, 3급은 그 회사
    # 자신의 변화 얘기가 아닌 건이다. 세 등급은 하나의 연속선(실현 → 착수 → 해당 없음)이다.
    #
    # ⚠️ 화면 표시 정책도 같은 날 바뀌었다(사용자가 두 번 뒤집었다).
    #   - 화면 쿼리는 이 필드를 읽지 않는다 — 정렬·선별에 쓰지 않는다(주요 이슈는 최신순).
    #   - 다만 헤드라인·주요 이슈 카드에 **등급 배지는 표시한다**(종전 "표시 금지"는 폐기).
    # 즉 판별선은 "등급이 화면에 보이는가"가 아니라 "등급이 무엇을 보여줄지 정하는가"다.
    # 상세는 docs/planning.md "승격 위계 등급" 절.
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
    # 축약본 2종 (2026-08-06, Report.content_short와 동일 패턴 — docs/planning.md "보고서
    # 길이 버전" 정책을 그대로 적용). 정본(content/implication)은 작성·검사의 기준이고, 이
    # 필드들은 정본에서 문장을 골라 빼기만 해 만든 표현이다(고쳐 쓰지 않음). 별도 문서가
    # 아니라 같은 인사이트의 두 번째 표현이므로 title/news는 버전 구분 없이 공유한다.
    # 축약은 정본 문장을 그대로 남기거나 빼는 것만 허용되므로 출처 무결성 점검은 정본에서
    # 1회만 돈다. RA가 아직 채우지 않은 기존 34건은 빈 문자열로 남으며, display_content /
    # display_implication이 정본으로 조용히 폴백한다(500 금지).
    content_short = models.TextField(blank=True)
    implication_short = models.TextField(blank=True)
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
        indexes = [
            # 🔴 2026-09-17 PE 신설(점검 지적 ⑤ — headliner_order 인덱스 0개,
            # 실측 Seq Scan cost 63.70). 대시보드 헤드라인
            # (apps/dashboard/views.py)이 filter(headliner_order__isnull=False)
            # .order_by("headliner_order")만 쓰므로 NULL(헤드라이너 아님 —
            # 대다수)을 뺀 부분 인덱스로 둔다. 전체 인덱스보다 작고, 이 쿼리
            # 모양과 정확히 맞는다(조건 없는 인덱스는 안 쓰는 대다수 NULL 행도
            # 함께 쌓아 두는 낭비다).
            models.Index(
                fields=["headliner_order"],
                name="insight_headliner_order_idx",
                condition=models.Q(headliner_order__isnull=False),
            ),
        ]

    def __str__(self):
        return self.title

    @property
    def display_content(self):
        """화면에 기본으로 보여줄 흐름 분석(축약본, 없으면 정본으로 폴백).

        Report.display_content와 동일 근거: 기본은 축약본이지만 비어 있을 수 있는 기존
        34건을 위해 조용히 정본으로 대체한다(500 금지).
        """
        return self.content_short or self.content

    @property
    def display_implication(self):
        """화면에 기본으로 보여줄 시사점(축약본, 없으면 정본으로 폴백). display_content와 동일 근거."""
        return self.implication_short or self.implication


class InsightNews(models.Model):
    insight = models.ForeignKey(Insight, on_delete=models.CASCADE)
    news = models.ForeignKey(News, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("insight", "news")
