from django.db import models
from apps.news.models import News, TagCorrectionRecord


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
    """🔴 폐기됨(2026-09-04, 사용자 확정) — SET-004(스케줄 관리) 화면과 그 화면이 쓰던
    services/scheduler.py(APScheduler)를 함께 지웠다. "사람이 눌러야만 돈다"(SET-010
    수동 실행 체제)를 깰 수 있는 마지막 자동 실행 경로였다 — pk=1이 is_active=False라
    지금은 안 걸렸지만, 화면에서 토글 한 번이면 사람 승인 없이 수집이 자동으로 돌기
    시작할 수 있었다.

    모델과 pk=1 레코드는 지우지 않고 남긴다. `last_run_at`(07/29 09:00)이
    `docs/planning.md` 여러 절이 인용하는 실측 근거이기 때문이다 — 이제 이 값을
    갱신하는 코드는 없으므로(그 값을 읽던 화면도 없다) 화석으로만 남는다. 이 테이블을
    다시 스케줄러에 등록하는 코드는 프로젝트 전체에 없다(ACTOR_CATCHUP과 같은 처리
    — 화면·코드는 없지만 과거 실측을 위해 데이터만 보존)."""

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

    # 수집 파이프라인 관측성 정책(docs/planning.md, 2026-08-04): 실행 주체를 구분해 기록한다.
    # "자동 수집이 도는가"를 판단하려면 수동 실행분이 섞이면 안 되기 때문이다. 기존 로그는 전부
    # _job_collect(스케줄) 경로에서만 남았던 것이 코드로 보증되므로, 그때는 default(ACTOR_SCHEDULED)로
    # 마이그레이션 시 그대로 백필했다.
    # 🔴 ACTOR_SCHEDULED: 폐기됨(2026-09-04) — 이 값을 만들어내던 services/scheduler.py와
    # SET-004 화면을 함께 지웠다(Schedule 모델 docstring 참고). 값은 지우지 않는다 —
    # 과거 CollectionLog에 이 값이 실제로 남아 있어(자동 스케줄 시절의 진짜 기록), 상수를
    # 지우면 그 로그의 choices 표시가 깨진다. 앞으로 이 값으로 새로 기록되는 로그는 없어야
    # 하므로(아래 actor default가 ACTOR_MANUAL로 바뀐 이유), 이 값이 보이면 전부 과거 기록이다.
    ACTOR_SCHEDULED = "자동(스케줄)"
    ACTOR_MANUAL = "수동(화면)"
    # ⚠️ ACTOR_CATCHUP: 기동 시 당일 수집 보정(catch-up) 기능은 2026-08-04에 도입했다가 같은 날
    # 철회됐다(개발 중 autoreload마다 실제 수집이 반복 실행되는 사고로 이어졌고, 상시 구동 서버로
    # 가면 애초에 필요 없어지는 기능이라 임시 환경만을 위한 영구 훅을 두지 않기로 결정 — "서버가
    # 꺼져 있으면 그날 수집이 안 되는 것"은 정상 동작으로 감수한다). 이 값을 실제로 만들어내는
    # 코드는 현재 없다(services/scheduler.py에 catch_up() 없음) — DB에 남아 있을 수 있는 과거
    # catch-up 로그를 조회·구분하기 위한 값만 남겨 둔다. 향후 옵션 B(상시 구동 서버) 착수 시
    # catch-up이 다시 필요해지면 이 값을 재사용할 수 있다.
    ACTOR_CATCHUP = "자동 복구(catch-up)"
    ACTOR_CHOICES = [
        (ACTOR_SCHEDULED, "자동(스케줄)"),
        (ACTOR_MANUAL, "수동(화면)"),
        (ACTOR_CATCHUP, "자동 복구(catch-up)"),
    ]

    source = models.ForeignKey(DataSource, on_delete=models.SET_NULL, null=True, related_name="logs")
    started_at = models.DateTimeField()
    collected_count = models.IntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    error_message = models.TextField(null=True, blank=True)
    # default는 ACTOR_MANUAL이다(2026-09-04, 스케줄 폐기와 함께 변경) — 스케줄이 없어진
    # 뒤로는 actor를 명시하지 않고 CollectionLog를 만드는 경로가 생기면 그게 곧 "지금
    # 실행 주체가 수동"이라는 뜻이어야 한다. 예전처럼 ACTOR_SCHEDULED를 기본값으로 두면
    # 관측성 정책이 없애려던 "자동(스케줄)"이라는 거짓 로그가 새로 만들어진다.
    actor = models.CharField(max_length=20, choices=ACTOR_CHOICES, default=ACTOR_MANUAL)
    # 크롤 실패 관측성(2026-08-19, PE 작업 배경: 본문이 152자만 수집된 기사가 조용히 저장돼
    # 관련성 판정 근거가 부실해졌고, 결국 KB금융 별칭 오매칭으로 이어져 News·Insight를 함께
    # 삭제한 사고가 실제로 있었다). 실패 판정 자체는 새로 만든 게 아니라
    # services/crawler.py의 기존 MIN_BODY_LENGTH=200 임계값(사고 사례 152자보다 크므로 이미 그 사고를
    # 잡아냈을 값)을 그대로 쓴다 — collector.py의 collect_naver()가 fetch_article_body()가 None을
    # 반환한(추출 실패 또는 200자 미만) 건수를 stats["crawl_failed"]로 이미 세고 있었는데 지금까지는
    # 그 값이 수집 직후 화면(_collect_result.html)에서만 잠깐 보이고 사라졌다 — 로그에 남지 않아 나중에
    # (사고처럼 태깅 오류를 역추적할 때) 확인할 방법이 없었다. 이 필드는 그 값을 CollectionLog에
    # 영속화해 SET-006 처리 이력에서도 볼 수 있게 한다. 수집 동작 자체(저장 여부)는 바꾸지 않는다 —
    # 실패해도 스니펫으로 계속 저장하고, 이 필드는 "실패를 드러낸다"만 한다.
    crawl_failed_count = models.IntegerField(default=0)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.started_at:%Y-%m-%d %H:%M} — {self.status} ({self.actor})"


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


class RunJob(models.Model):
    """SET-010 실행 한 번(docs/planning.md "1번을 LLM으로 옮기는 설계" 4-(a) "RunJob —
    실행 한 번"). 화면 버튼이나 관리 명령이 누른 작업 하나의 생애주기를 담는다.

    🔴 요청 밖 워커 스레드가 진행 상황을 쓰는 유일한 저장소다. gunicorn 워커가 여럿이면
    스레드가 뜬 워커와 폴링이 오는 워커가 다를 수 있어(같은 문서 "실행 모델" 3-(c)),
    전역 변수나 모듈 상태로 진행 상황을 들고 있으면 폴링이 그것을 보지 못한다. 그래서
    진행 건수와 상태는 예외 없이 이 테이블에 쓴다 — services/runner.py가 유일하게
    이 테이블에 쓰는 코드이고, 읽는 쪽(apps/setting/views.py)은 조회만 한다.

    🔴 상태 7가지 중 `완료`와 `확정됨`을 반드시 구분한다 — 판정이 끝난 것과 사람이
    확정 버튼을 누른 것은 다른 사건이고, 합치면 승인 게이트가 상태 위에서 사라진다.
    이번 라운드(수집만 실제로 돈다)는 확정 게이트가 없는 작업이라 `확정됨`까지 가는
    경로가 없지만, 2라운드의 `cleanup`이 그 경로를 쓸 수 있도록 값 자체는 지금 만들어
    둔다.
    """

    STATUS_PENDING = "대기"
    STATUS_RUNNING = "진행중"
    STATUS_DONE = "완료"
    STATUS_FAILED = "실패"
    STATUS_STOPPED = "중단됨"
    STATUS_CONFIRMED = "확정됨"
    STATUS_CANCELED = "취소됨"
    STATUS_CHOICES = [
        (STATUS_PENDING, "대기"),
        (STATUS_RUNNING, "진행중"),
        (STATUS_DONE, "완료"),
        (STATUS_FAILED, "실패"),
        (STATUS_STOPPED, "중단됨"),
        (STATUS_CONFIRMED, "확정됨"),
        (STATUS_CANCELED, "취소됨"),
    ]

    ACTOR_SCREEN = "화면"
    ACTOR_COMMAND = "관리 명령"
    ACTOR_CHOICES = [
        (ACTOR_SCREEN, "화면"),
        (ACTOR_COMMAND, "관리 명령"),
    ]

    job_key = models.CharField(
        max_length=30, db_index=True,
        help_text="apps/setting/views.py RUN_JOB_KEYS의 값(collect, cleanup 등). 그 목록이 "
                   "계속 늘 수 있어 고정 choices로 박지 않는다 — DeletedNewsRecord.criterion_code와 "
                   "같은 이유(docs/planning.md '판정 기록 보존 정책' 1번).",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # 하트비트 — 워커 스레드가 진행마다(이번 라운드는 키워드 1개 처리마다) 갱신한다.
    # 별도 감시 프로세스는 없다. 읽는 쪽(services/runner.py의 mark_stale_running_as_stopped())이
    # 화면 요청이 들어올 때마다 이 값과 지금 시각의 차이를 보고 판정한다(같은 문서 3-(e)).
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    target_count = models.IntegerField(default=0)
    processed_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    actor = models.CharField(max_length=20, choices=ACTOR_CHOICES, default=ACTOR_SCREEN)
    # 🔴 이번 라운드는 필드만 만들고 비워 둔다 — 수집에는 채울 프롬프트 버전이 없다
    # (docs/planning.md 같은 절 "🔴 프롬프트 버전은 필드만 만들고 비워 둡니다").
    prompt_version = models.CharField(max_length=50, blank=True, default="")

    class Meta:
        ordering = ["-started_at", "-pk"]
        constraints = [
            # 진행중(STATUS_RUNNING="진행중") 행은 시스템 전체에 최대 1개만 허용한다.
            # "같은 job이 이미 진행중이면 못 누르게"(문서 3-(g))가 요구하는 최소치는
            # job_key 단위 잠금이지만, run.html의 기존 화면 계약이 이미 축을 넘는 전역
            # 잠금이다(_run_graph.html "🔴 잠금은 축을 넘어 전역이다" — LLM/외부 API가
            # 하나라 두 축을 동시에 돌리면 비용과 rate limit이 겹친다). 잠금 범위가
            # 화면과 DB에서 어긋나면 "화면엔 하나만 도는 것처럼 보이는데 실제로는 둘이
            # 돈다"는 불일치가 생기므로, DB 제약도 화면과 같은 전역 범위로 맞춘다.
            # status 필드 자체에 조건부 유니크를 걸면(조건을 만족하는 행은 전부 값이
            # "진행중"으로 같으므로) "진행중인 행은 전체에서 1개"가 강제된다.
            models.UniqueConstraint(
                fields=["status"],
                condition=models.Q(status="진행중"),
                name="unique_running_run_job",
            ),
        ]

    def __str__(self):
        return f"{self.job_key} — {self.status}"


class RunProposal(models.Model):
    """SET-010 제안 한 건(docs/planning.md 같은 절 4-(b) "RunProposal — 제안 한 건").

    🔴 이번 라운드는 모델과 마이그레이션만 세운다 — 행은 만들지 않는다. services/llm.py가
    비어 있어 판정 자체가 없기 때문이다. 2라운드에서 뒤늦게 만들면 마이그레이션이
    쪼개져 되돌리기가 어려워지므로 지금 함께 세운다(오케스트레이터 지시).

    🔴 `target_name`과 `axis`는 docs/planning.md 4-(b)에 PM이 정식으로 편입한 필드다
    (2026-09-14) — 처음 구현 때는 문서 밖 추가였지만 지금은 설계 그 자체다. 둘 다
    "태그 제거"/"태그 추가" 제안이 확정될 때 `correct_news_tag(news, target, action=...)`를
    실제로 실행하는 데 필요하다 — `target_name`만으로는 그 이름이 `Organization`인지
    `TechTopic`인지 알 수 없고(`correct_news_tag()`는 객체를 받아 축을 자동 판별하지,
    이름 문자열만으로는 판별할 수 없다), `axis`가 그 축을 담는다. 값은
    `TagCorrectionRecord.axis`와 같은 어휘를 그대로 참조해 쓴다(드리프트 방지, 아래
    필드 정의 참고).

    ⚠️ **왜 FK가 아니라 문자열인가(target_name·axis 공통, PM 확정 근거)**
    1. 확정되면 이 값이 그대로 `TagCorrectionRecord.target_name`(문자열)이 된다.
       타입이 다르면 그 사이에 변환이 생기고, 변환이 있는 자리가 곧 어긋나는 자리다.
    2. 🔴 LLM이 내놓는 것이 애초에 이름이다. FK라면 저장 시점에 대상 해석이 끝나
       있어야 하는데, **"해석 실패"(본문의 핵심 주체가 `Organization`에 아직 없는
       경우)가 바로 이 파이프라인이 다뤄야 하는 상황**이다(docs/planning.md 4-(b)
       "미등록 기업은 제안만 하고 등록하지 않는다"). FK로는 그런 제안 자체를 만들 수
       없다.
    3. 확정 후에도 남는 이력이므로, 대상이 나중에 개명·비활성화돼도 제안 당시 값이
       그대로 남아야 한다는 근거(TagCorrectionRecord.target_name과 동일)도 함께
       적용된다.

    **대가**: 확정 시점에 이 이름으로 실제 Organization/TechTopic을 찾지 못할 수 있다
    (그사이 개명·삭제됐거나, LLM이 존재하지 않는 이름을 냈거나). 그때는 **그 제안
    하나만 실패로 남기고 나머지 제안은 그대로 확정한다** — 확정 전체를 막지 않는다
    (2라운드에서 확정 뷰를 구현할 때 지킬 규칙).

    🔴 **행은 태그 하나당 하나다.** 한 행에 여러 태그를 담지 않는다 — 사람이 검토
    화면에서 태그 단위로 채택/거절을 갈라야 하고("셋을 떼자고 했는데 둘만 맞다"가
    실제 경로), 묶으면 「삭제 제안과 태그 제안을 따로 확정한다」가 지키려던 것이
    태그들 사이에서 다시 무너진다. 거절 분포로 프롬프트 정확도를 재는 관측(4-(b)
    "이것이 프롬프트 정확도를 잴 유일한 정답지")도 묶으면 셀 수 없어진다.

    ⚠️ 대상 `News` FK에 unique를 걸지 않는다 — 한 기사에 제안이 여러 개(예: 삭제 제안
    1개 + 태그 제거 제안 2개) 달릴 수 있다.
    """

    TYPE_DELETE = "삭제"
    TYPE_KEEP = "유지"
    TYPE_TAG_REMOVE = "태그 제거"
    TYPE_TAG_ADD = "태그 추가"
    # 🔴 5번째 종류(2026-09-14, 2라운드 PE 신설) — docs/planning.md 4-(b)가 열어 둔 자리다.
    # "미등록 기업은 제안만 하고 등록하지 않는다"(같은 문서) — LLM이 본문의 핵심 주체가
    # Organization에 없어 보인다고 판단하면 이 종류로 남긴다. axis는 항상 비워 둔다
    # (Organization/TechTopic 중 어느 쪽인지를 다투는 제안이 아니라 신규 등록 후보이므로
    # 축 자체가 없다). 확정 버튼도 이 종류는 등록을 실행하지 않는다 — 사람이 SET-007에서
    # 삼킴 검사를 거쳐 직접 등록한다.
    TYPE_ORG_CANDIDATE = "기업 후보"
    TYPE_CHOICES = [
        (TYPE_DELETE, "삭제"),
        (TYPE_KEEP, "유지"),
        (TYPE_TAG_REMOVE, "태그 제거"),
        (TYPE_TAG_ADD, "태그 추가"),
        (TYPE_ORG_CANDIDATE, "기업 후보"),
    ]

    STATUS_PENDING = "대기"
    STATUS_ACCEPTED = "채택"
    STATUS_REJECTED = "거절"
    STATUS_CANCELED = "취소"
    STATUS_CHOICES = [
        (STATUS_PENDING, "대기"),
        (STATUS_ACCEPTED, "채택"),
        (STATUS_REJECTED, "거절"),
        (STATUS_CANCELED, "취소"),
    ]

    run_job = models.ForeignKey(RunJob, on_delete=models.CASCADE, related_name="proposals")
    # LLMLog.news와 같은 이유로 SET_NULL + null=True다 — 채택된 삭제 제안이 확정되면
    # delete_news_with_record()가 대상 News 자체를 지운다. CASCADE였다면 그 순간 이
    # 제안 행(감사 기록)까지 함께 사라져 "무엇을 왜 제안했는가"가 남지 않는다. 거절된
    # 제안은 News가 그대로 남으므로 FK도 그대로 유지된다.
    # unique를 걸지 않는다 — 한 기사에 제안이 여러 개(삭제 1 + 태그 제거 2 등) 달릴 수 있다.
    news = models.ForeignKey(News, on_delete=models.SET_NULL, null=True, blank=True, related_name="run_proposals")
    proposal_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    # DeletedNewsRecord.criterion_code와 같은 이유로 자유 문자열이다 — 판정 기준 개정이
    # 잦아 enum으로 박지 않는다(docs/planning.md "판정 기록 보존 정책" 1번).
    criterion_code = models.CharField(max_length=20, blank=True)
    reason = models.TextField(blank=True)
    target_name = models.CharField(
        max_length=200, blank=True,
        help_text="태그 제거/추가 제안의 대상 Organization/TechTopic 이름. 삭제/유지 제안은 비워 둔다. "
                   "FK가 아니라 문자열인 이유는 클래스 docstring 참고.",
    )
    # TagCorrectionRecord.axis와 같은 값을 그대로 참조한다(자체 상수를 새로 만들지 않음 —
    # 드리프트 방지). correct_news_tag()가 target 객체 타입으로 축을 자동 판별하는데,
    # RunProposal은 target을 이름 문자열(target_name)로만 들고 있어 그 판별을 대신할
    # 값이 필요하다.
    axis = models.CharField(
        max_length=20, choices=TagCorrectionRecord.AXIS_CHOICES, blank=True,
        help_text="태그 제거/추가 제안의 축(기업/기술 주제). 삭제/유지 제안은 비워 둔다. "
                   "FK가 아니라 문자열인 이유는 클래스 docstring 참고.",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    judged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-judged_at", "-pk"]

    def __str__(self):
        return f"RunProposal({self.proposal_type}, news={self.news_id})"
