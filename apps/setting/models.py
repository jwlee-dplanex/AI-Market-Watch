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
