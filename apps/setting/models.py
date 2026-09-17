from django.db import models
from apps.news.models import DeletedNewsRecord, Insight, News, TagCorrectionRecord
from apps.reports.models import Report


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
    확정 버튼을 누른 것은 다른 사건이고, 합치면 휴먼 인 더 루프가 상태 위에서 사라진다.
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
    # 🔴 2026-09-15 PE 신설 — services/llm.py classify_news()가 반환하는 _usage를 담을
    # 자리가 그동안 없어(RunJob에도 LLMLog에도 저장되지 않아) 실제 토큰 데이터가 전혀
    # 없었다(오케스트레이터 지적). count_tokens가 Bedrock에서 지원되지 않아 응답 usage가
    # 비용을 재는 유일한 수단인데 그 값을 버리고 있었다.
    #
    # 건별이 아니라 RunJob(배치) 단위 합계로 둔 이유:
    # ① review.step.tokens(검토 화면 "AI가 한 일" 칸)가 읽는 값은 배치 전체의 토큰
    #    합계이지 건별 값이 아니다 — apps/setting/views.py `_run_review_context()` 참고.
    # ② PM이 비용 산식을 갱신하려면 "배치 전체에 입력/출력/캐시 생성/캐시 읽기 토큰이
    #    각각 얼마나 들었는가"만 있으면 된다 — 캐시 생성은 배치 첫 건에서 한 번만 크게
    #    잡히고 나머지는 캐시 읽기이므로, 배치 합계만으로도 그 비율(캐시 적중률)이
    #    그대로 드러난다. 건별 값이 추가로 밝혀 주는 것은 기사 본문 길이에 따른 편차뿐인데,
    #    지금 비용 산식이 요구하는 것은 그 편차가 아니라 배치 총비용이다.
    # ③ 건별로 남기면 행이 계속 늘어난다(2026-09-15까지 두 배치 139건) — 최소 구현
    #    원칙상, 지금 실제로 필요한 것(①·②)을 넘어서는 저장 구조를 미리 만들지 않는다.
    #    건별 편차 분석이 실제로 필요해지면(예: 프롬프트가 더 길어져 기사 길이별 비용
    #    차이를 추적해야 할 때) 그때 건별 로그를 별도로 추가한다.
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    cache_creation_input_tokens = models.IntegerField(default=0)
    cache_read_input_tokens = models.IntegerField(default=0)
    # 🔴 2026-09-15 PE 신설 — "newsroom_filter" 전용(다른 job_key는 항상 0).
    # docs/planning.md 뉴스룸 정책 13-6 PE 인계 5번 "걸린 건수를 실행 산출물에
    # 남긴다" — 13-4 재개봉 조건("서로 다른 3배치 연속으로…")을 체감이 아니라
    # 이 값을 보고 판단하기 위한 자리다. processed_count(전체 처리 건)와는 다른
    # 질문에 답한다 — "그중 제목 규칙에 걸린 건이 몇이었는가."
    title_rejected_count = models.IntegerField(default=0)
    # 🔴 2026-09-16 PE 신설(docs/planning.md "2단계 비용 절감 정책" 회귀 검사,
    # docs/design.md "SET-010 · 실행" 21차 개정 ⑧번) — "cleanup" 전용. 이 확정으로
    # 검증됨으로 넘어간 News 중 사전 차단 규칙(services/cleanup_prefilter.py)을 다시
    # 돌렸을 때 걸리는 건수. 확정 뷰가 채운다. 검토 화면이 "가장 최근 확정된 cleanup
    # RunJob"의 이 값을 읽어 step.notice에 반영한다 — messages.warning은 확정 직후
    # 한 번 뜨고 사라지지만, 낱말 목록을 넓히는 일은 코드를 고쳐야 해서 사용자가 그
    # 자리에서 처리할 수 없어 다음 화면 진입에서도 남아 있어야 한다.
    regression_flag_count = models.IntegerField(default=0)
    # 🔴 2026-09-16 "SET-010 검토 단위" 절 13번 신설 — 확정 버튼을 누른 시각. 종전에는
    # 화면 요약 줄이 finished_at(실행 종료 시각)을 "확정 시각"으로 대신 썼는데, 어제
    # 실행하고 오늘 확정하면 어제로 찍혔다. 여러 배치를 한 번에 확정하는 이번 설계에서
    # 이 어긋남이 정상 경로가 됐으므로(SET-010 검토 단위 절) 더 미룰 수 없다. 같은
    # 확정 한 번에 묶인 배치는 전부 같은 값을 갖는다.
    confirmed_at = models.DateTimeField(null=True, blank=True)
    # 🔴 3단계(주요 이슈) 탈락 표식의 전제 — 그 확정 시점에 "이 배치가 후보로 고려한
    # News 전부"를 얼려 둔다(docs/planning.md "SET-010 검토 단위" 절 11번). RunDraft.news는
    # "이슈로 묶인 것"만 담아 "고려했지만 어디에도 안 묶인 것"을 알 방법이 없어 새로
    # 만들었다 — 확정 시 이 집합에서 실제로 채택된 Insight의 news를 뺀 나머지가
    # News.insight_dismissed_at을 받는다. job_key="insight"가 아닌 RunJob은 채우지 않는다.
    insight_candidates = models.ManyToManyField("news.News", blank=True, related_name="+")
    # 🔴 2026-09-16 23차 개정(docs/planning.md 「SET-010 실행 중단」 2번, 9-1) — 「사람이
    # 언제 멈춰 달라고 했는가」를 적는 칸. STATUS_* 어휘는 늘리지 않는다 — 값을 늘리면
    # 그 값을 읽는 분기가 전부 두 벌이 되고, 한 곳만 빠뜨리면 배치가 확정할 수 없는
    # 상태로 갇힌다(같은 문서 2번). 이 칸 하나가 두 가지 일을 겸한다 — (a) 돌고 있는
    # 루프가 매 경계에서 읽는 중단 신호(services/runner.py), (b) 끝난 뒤에는 「사고가
    # 아니라 사람이 멈춘 것」이라는 증거(apps/setting/views.py 사고 배지 판정). 비어
    # 있으면 하트비트 판정으로 끊긴 것이고, 차 있으면 사람이 멈춘 것이다.
    stop_requested_at = models.DateTimeField(null=True, blank=True)
    # 🔴 2026-09-17 신설(docs/planning.md "RA 손 작업을 전부 단계 안으로 넣는다" 2-3번,
    # docs/design.md 31차 ⑩ "1-B 창 기록 의무를 코드가 적는 자리가 여기다") — job_key
    # "insight"인 RunJob만 채운다. 창·기준점·후보 수는 3단계 세 번째 호출(헤드라인 순위)
    # 시점에 코드가 계산한 값이라, 검토 화면이 다시 계산하지 않고 그때 적힌 값을 그대로
    # 읽는다 — 재계산하면 "생성 시점의 창"과 "검토 시점에 다시 잰 창"이 어긋날 수 있다.
    headliner_window_label = models.CharField(
        max_length=200, blank=True, default="",
        help_text='예: "창 7일 · 기준점 09.16 · 후보 1급 9건". job_key="insight"만 채운다.',
    )
    # 🔴 같은 절 — 직전 헤드라인 지정 중 이번에 빠진 것들. [{"prev_rank", "title", "reason"}].
    # 5-2 교체 기록 의무의 절반(무엇이 빠졌는가)이 여기 남는다 — 남은 절반(무엇이
    # 들어왔는가)은 RunDraft.headliner_change/headliner_change_reason이 진다.
    headliner_dropped = models.JSONField(default=list, blank=True)
    # 🔴 2026-09-17 PE 신설(docs/planning.md "지식그래프 관계 라벨링을 3단계의 두 번째
    # LLM 호출로 옮긴다" 6번·13번 PE 인계 5번) — job_key="insight"만 채운다. 관계 제안
    # 생성 시점에 이미 OrgRelation이 있는 쌍은 제안 자체를 만들지 않는다(정책 6번 —
    # 확정 시점이 아니라 제안 생성 시점에 거른다, update_or_create가 사람이 쓴
    # description을 갈아엎기 때문). 그 걸러낸 건수를 여기 남긴다 — 안 남기면 "LLM이
    # 놓쳤다"는 오해가 생긴다(templates/setting/run_review.html relation_skipped_count
    # 계약. PD가 이미 화면을 그려 뒀는데 생성 쪽이 이 값을 채운 적이 없어 항상 비어
    # 있었다). services/runner.py가 채우고, 검토 화면은 조회만 한다
    # (headliner_window_label과 같은 패턴).
    relation_skipped_count = models.IntegerField(default=0)
    # 🔴 같은 절 — 건너뛴 쌍 중 LLM이 기존과 다른 라벨을 본 쌍 수(선택 관측치, 정책
    # 6번 "잃는 것을 관측으로 남긴다"). RA가 배치 보고서에 옮겨 적어 2회 누적되면
    # PM이 관계 변천 경로를 연다(14번 되돌림 조건).
    relation_conflict_count = models.IntegerField(default=0)
    # 🔴 2026-09-17 PE 신설(docs/planning.md "3단계 비용 구조 — 관계 호출의 입력을
    # 좁힌다" 11-1-(e) ⓐ) — job_key="insight"만 채운다. 관계 호출(두 번째 LLM
    # 호출)에 실제로 들어간 News 건수, 즉 filter_relation_targets()를 거쳐 「금융사·
    # 보험사 태그 1개 이상 그리고 AI 기업 태그 1개 이상」을 만족한 건수다(B안). 3단계
    # 입력 전체(M)는 이미 target_count가 진다 — job_key="insight"에서 target_count는
    # 관계 필터와 무관하게 이슈 판정 대상 전체로 한 번만 채워진다. 이 로그(N)가
    # target_count(M)보다 먼저 존재해야 필터를 켤 수 있다(11-1-(e) ⓐ "이 기록이
    # 없으면 B를 켜지 않는다") — RA가 "본문에 관계가 있는데 제안에 없는 기사"를
    # 발견했을 때 N과 M을 비교해 필터 탓인지 LLM이 놓친 것인지 가르는 유일한 수단.
    relation_target_count = models.IntegerField(default=0)

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
    # 🔴 5번째 종류(2026-09-14, 2라운드 PE 신설. 2026-09-15 `기업 후보`에서 `태그 후보`로
    # 일반화 — docs/planning.md 4-(b) 🔴 개정 (2026-09-15)). "미등록 기업/기술 주제는
    # 제안만 하고 등록하지 않는다"(같은 문서) — LLM이 본문의 핵심 주체가 Organization·
    # TechTopic 어느 쪽에도 없어 보인다고 판단하면 이 종류로 남긴다. `axis`는 그 대상이
    # 기업인지 기술 주제인지를 담는다(TYPE_TAG_ADD/TYPE_TAG_REMOVE와 같은 방식 — 아래
    # axis 필드 정의 참고). 확정 버튼도 이 종류는 등록을 실행하지 않는다 — 사람이
    # SET-007(기업) 또는 SET-008(기술 주제)에서 삼킴 검사를 거쳐 직접 등록한다.
    #
    # 별도 종류를 신설하지 않고 기존 `기업 후보`를 일반화한 이유는 위 문서 개정 절 참고 —
    # 두 축의 성격 차이는 SET-007/SET-008의 등록 판단에서 갈리지, 제안 레코드의 모양에서
    # 갈리지 않는다. 확정해도 아무 동작이 없고, 확정 버튼이 열리는 커버리지 조건에서
    # 빠지는 성질은 그대로 상속된다.
    TYPE_TAG_CANDIDATE = "태그 후보"
    # 🔴 6번째 종류(2026-09-17 28차 정정 신설, docs/design.md "SET-010 · 실행" 28차
    # 정정 ⑤번) — 기준 2(동일 사건 중복 보도)로 판정된 기사. services/runner.py의
    # _run_dedup()이 만든다(다음 라운드 배선 — 이번 라운드는 화면·모델·확정 뷰
    # 플러밍만 세운다). TYPE_DELETE와 다른 종류로 가른 이유는 처분이 다르기
    # 때문이다 — 확정하면 대상 News를 지우지 않고 News.duplicate_of에
    # duplicate_representative를 채워 감춘다(아래 필드 정의 참고). 같은 처분이라도
    # TYPE_DELETE로 두면 확정 뷰가 "지울 것"과 "감출 것"을 DB에서 되짚어 구분해야
    # 하는데, 27차가 insight_ids/draft_ids를 가른 것과 같은 이유로 이름(=타입)을
    # 가르는 쪽을 택했다.
    TYPE_DUPLICATE = "중복 보도"
    TYPE_CHOICES = [
        (TYPE_DELETE, "삭제"),
        (TYPE_KEEP, "유지"),
        (TYPE_TAG_REMOVE, "태그 제거"),
        (TYPE_TAG_ADD, "태그 추가"),
        (TYPE_TAG_CANDIDATE, "태그 후보"),
        (TYPE_DUPLICATE, "중복 보도"),
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
        help_text="태그 제거/추가/후보 제안의 축(기업/기술 주제). 삭제/유지 제안은 비워 둔다. "
                   "FK가 아니라 문자열인 이유는 클래스 docstring 참고.",
    )

    # 🔴 TYPE_DUPLICATE 전용 필드 셋(2026-09-17 28차 정정 신설, docs/design.md
    # "SET-010 · 실행" 28차 정정 ⑤번 "대표 pk를 화면이 보내지 않는다 ... RunProposal이
    # 자기 묶음의 대표 News.pk를 들고 있어야 한다. 이 값이 없으면 duplicate_of에 넣을
    # 것이 없다 — 모델 쪽에서 먼저 확인할 자리다").
    #
    # 대표 기사 자신에게는 RunProposal 행이 없다 — 대표는 "지울/감출 제안"이 아니라
    # "이 묶음에서 남을 기사"이기 때문이다(검토 화면이 폼으로 보낼 대표 pk가 없는 이유,
    # 같은 절 ⑤-1). 그래서 감출 각 행이 자기 묶음의 대표를 직접 들고 있어야 확정 뷰가
    # News.duplicate_of에 채울 값을 얻는다 — 별도 그룹 테이블을 두지 않는 대신, 같은
    # 묶음의 행은 아래 세 필드에 같은 값을 중복해 담는다(criterion_code/reason처럼
    # 행마다 자기 완결적으로 담는 이 모델의 기존 패턴을 그대로 따른다).
    duplicate_representative = models.ForeignKey(
        News, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="TYPE_DUPLICATE 제안이 속한 묶음의 대표 News. 확정하면 대상 News.duplicate_of에 "
                   "이 값이 들어간다(삭제하지 않는다). 삭제/유지/태그 제안은 비워 둔다.",
    )
    # 검토 화면 「공통 표현」 배지(design.md 28차 ①-2 — "사람이 '왜 이 셋이 같은
    # 보도인가'에 답하는 유일한 근거"). 대표 포함 같은 묶음의 모든 행이 같은 값을 갖는다.
    dup_fingerprint = models.JSONField(
        default=list, blank=True,
        help_text="TYPE_DUPLICATE 제안이 속한 묶음의 공통 표현 토큰 목록(예: ['ADAS', '이미지 "
                   "판독']). 같은 묶음의 행은 같은 값을 중복해 담는다. 그 외 제안은 빈 리스트다.",
    )
    DUP_PICK_REASON_EXISTING = "existing"
    DUP_PICK_REASON_LONGEST = "longest"
    DUP_PICK_REASON_LINKED = "linked"
    DUP_PICK_REASON_CHOICES = [
        (DUP_PICK_REASON_EXISTING, "기존분"),
        (DUP_PICK_REASON_LONGEST, "본문 최장"),
        (DUP_PICK_REASON_LINKED, "근거 있음"),
    ]
    # 대표를 고른 이유(design.md 28차 ③-3 "대표 선정 이유를 한 낱말로 찍는다").
    # 🔴 화면 배지 낱말("기존분"/"본문 최장"/"근거 있음")은 템플릿이 가진다 — 여기는
    # 코드값만 담는다(reason과 달리 이 낱말 자체는 DB로 넘어가는 보존 자산이 아니라
    # 화면 표시라는 판단, 같은 절).
    dup_pick_reason = models.CharField(
        max_length=20, choices=DUP_PICK_REASON_CHOICES, blank=True, default="",
        help_text="duplicate_representative를 고른 이유. TYPE_DUPLICATE 제안에만 채운다.",
    )

    # 🔴 2026-09-16 PE 신설(docs/planning.md "2단계 비용 절감 정책" 4-3번, 형식 요건
    # 3번) — 이 삭제/유지 제안을 낸 주체가 LLM인지 코드(사전 차단 규칙)인지 남긴다.
    # 빈 값(기본값)은 지금까지처럼 LLM(classify_news()) 판정이라는 뜻이다 — 이번에
    # LLM 경로를 건드리지 않아 기존 행의 의미가 그대로 유지된다. 코드가 낸 제안만
    # DeletedNewsRecord 판정 주체 어휘를 그대로 채운다(자체 상수를 새로 만들지 않음 —
    # TagCorrectionRecord.JUDGED_BY_RA가 DeletedNewsRecord.JUDGED_BY_RA를 그대로
    # 참조하는 것과 같은 드리프트 방지 이유). 확정 뷰(setting_run_review_confirm)가
    # 이 값을 그대로 delete_news_with_record(judged_by=...)에 넘긴다 — 규칙 정확도와
    # LLM 정확도가 한 통계에 섞이지 않게 하려는 목적이다.
    JUDGED_BY_CODE_AI_KEYWORD_RULE = DeletedNewsRecord.JUDGED_BY_CODE_AI_KEYWORD_RULE
    judged_by = models.CharField(
        max_length=30, blank=True, default="",
        help_text=f"빈 값=LLM 판정. 코드 사전 차단 제안만 '{JUDGED_BY_CODE_AI_KEYWORD_RULE}'를 채운다.",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    judged_at = models.DateTimeField(auto_now_add=True)

    # 🔴 사후 뒤집힘(2026-09-15 PM 결정, docs/planning.md 4-(b) "🔴 개정 (2026-09-15)
    # 정답지에 구멍이 있다") — `RunProposal.status`만 보면 확정 뒤에 사람이 뒤집은
    # 유지 제안이 여전히 `채택`으로 보여 프롬프트 정확도가 거짓으로 100%가 된다
    # (실측: RunProposal 110·293. 유지 제안 정확도가 `status`만 보면 17/17인데
    # 실제는 15/17이었다).
    #
    # `status`를 새 값으로 덮어쓰지 않고(그러면 "확정 시점에 사람이 이걸 받았다"는
    # 사실이 사라진다) 칸을 하나 더 두는 이유는 PM 결정 그대로다 — `status`는
    # 원래부터 사후에 바뀌는 칸이고, 제안 당시 기록을 지고 있는 것은 proposal_type·
    # criterion_code·reason 셋이라 이 개정이 그 셋을 건드리지 않기 때문이다.
    #
    # 🔴 이 두 필드는 사람이 기억해서 채우지 않는다. `apps/news/services.py`의
    # `delete_news_with_record()`가 채택된 `유지` 제안을 가진 News가 삭제되는 순간
    # 자동으로 채운다(RA가 배치 확정 뒤 오판을 발견해 그 자리에서 삭제할 때가 주
    # 경로다) — 쓰는 쪽을 사람의 성실성 밖으로 빼는 것이 이 결정의 본체다.
    #
    # ⚠️ 뒤집기 전용 사유 칸은 따로 두지 않는다 — 사유와 기준 코드는 그 삭제가 남기는
    # DeletedNewsRecord.reason/criterion_code에 이미 있다. 같은 값을 두 곳에 두면
    # 갈린다.
    reversed_at = models.DateTimeField(
        null=True, blank=True,
        help_text="이 제안(채택된 '유지')이 확정 뒤에 뒤집혀 삭제된 시각. "
                   "delete_news_with_record()가 자동으로 채운다. judged_at은 제안이 "
                   "만들어진 시각이라 이 값에 쓸 수 없다(auto_now_add).",
    )
    reversed_by = models.CharField(
        max_length=30, blank=True,
        help_text="뒤집은 주체. DeletedNewsRecord 판정 주체 어휘를 그대로 쓴다(RA / "
                   "사용자(화면 삭제) / 소급 정비 / 자동 판정) — delete_news_with_record() "
                   "호출 시 넘긴 judged_by 값이 그대로 들어온다.",
    )

    # 🔴 2026-09-17 신설(docs/planning.md "검토 결과를 고도화 재료로 쓴다" 2·3번,
    # 2026-09-17 사용자 확정) — 거절(status=STATUS_REJECTED)에 "누가 받는가"를
    # 한 번 고르게 하는 칸 둘. 삭제 제안에만 붙는다(태그 교정 행에는 오지 않는다,
    # 같은 문서 2번 "삭제 기준 코드 어휘를 재사용하지 않는다"와 짝을 이루는 별도
    # 어휘). 자유 문자열이다("판정 기록 보존 정책" 1번과 같은 근거 — choices로
    # 박으면 어휘 개정마다 마이그레이션이 필요해진다).
    #
    # 🔴 28차 정정(2026-09-17, docs/design.md "SET-010 · 실행" 28차 정정 ⑤번) —
    # TYPE_DUPLICATE(중복 보도)의 감출 행에도 그대로 붙는다. 체크를 푸는 것이
    # 「거절」인 자리라 형태가 같다 — "삭제 제안에만"이라는 아래 help_text는 확정
    # 대상 종류가 삭제/유지에서 삭제/유지/중복 보도로 늘어난 지금도 "체크박스를 가진
    # 종류"라는 뜻으로는 그대로다(태그 교정 행에는 여전히 오지 않는다).
    #
    # 어휘 넷 — 오적용(PE가 프롬프트를 고친다) / 기준재검토(PM이 이 문서의 판정
    # 기준을 먼저 고친다) / 기타(자유 서술 필수) / 미기입(안 고름). 넷 다 이
    # CharField 안의 값일 뿐 choices 제약은 걸지 않는다.
    #
    # 🔴 required가 아니다 — 안 고르면 확정 뷰가 "미기입"으로 저장하고 확정을
    # 그대로 진행한다(같은 문서 "체크를 푸는 일이 비싸지면 사람은 거절을 피하고
    # 그냥 확정을 누른다"). 값을 쓰는 것은 status=STATUS_REJECTED가 된 행뿐이다 —
    # 채택되거나 취소된 행에는 이 칸을 채우지 않는다(x-show가 감추기만 해서 DOM에
    # 남은 값이 그대로 실려 오는 것을 확정 뷰가 걸러낸다).
    REJECT_CODE_MISAPPLIED = "오적용"
    REJECT_CODE_CRITERIA_REVIEW = "기준재검토"
    REJECT_CODE_OTHER = "기타"
    REJECT_CODE_UNSPECIFIED = "미기입"
    reject_code = models.CharField(
        max_length=20, blank=True, default="",
        help_text=f"거절(status='{STATUS_REJECTED}')을 받을 사람. "
                   f"'{REJECT_CODE_MISAPPLIED}'(PE) / '{REJECT_CODE_CRITERIA_REVIEW}'(PM) / "
                   f"'{REJECT_CODE_OTHER}'(자유 서술 필수) / '{REJECT_CODE_UNSPECIFIED}'(안 고름). "
                   "자유 문자열이다. 삭제/중복 보도 제안에만 채운다 — 태그 교정 행은 항상 빈 값이다.",
    )
    reject_note = models.TextField(
        blank=True, default="",
        help_text=f"reject_code가 '{REJECT_CODE_OTHER}'일 때만 채우는 자유 서술.",
    )

    class Meta:
        ordering = ["-judged_at", "-pk"]
        indexes = [
            # 🔴 2026-09-17 PE 신설(점검 지적 ⑤ — _reject_stats_context()가 확정된
            # RunJob 전체 이력의 RunProposal을 무제한 스캔, 점검자가 "가장 먼저
            # 체감될 자리"로 지목). 그 함수가 매번 던지는
            # filter(run_job_id__in=...).filter(status=...) 모양과 맞춘 복합
            # 인덱스 — run_job이 선행 컬럼이라 run_job_id__in 자체도 그대로
            # 덕을 본다.
            #
            # ⚠️ 이 인덱스가 그 함수의 "누적 이력 전체를 본다"는 설계 자체를
            # 바꾸지는 않는다 — 화면에 보이는 집계 범위(수)는 손대지 않는다는
            # 제약(고친 뒤에도 화면 값이 하나도 달라지면 안 된다) 때문에 일부러
            # 그대로 뒀다. 인덱스는 상수 비용을 줄일 뿐 "이력이 계속 쌓이면
            # 언젠가 다시 느려진다"는 점근적 한계 자체는 그대로다 — 그 함수
            # docstring이 이미 적어 둔 트레이드오프고, 이 라운드에서 그 설계를
            # 다시 판단하지 않는다.
            models.Index(fields=["run_job", "status"], name="runproposal_runjob_status_idx"),
        ]

    def __str__(self):
        return f"RunProposal({self.proposal_type}, news={self.news_id})"


class RunDraft(models.Model):
    """SET-010 3~5단계(주요 이슈, 주간 보고서, 월간 보고서) 초안 한 건
    (docs/planning.md "3~5단계를 LLM으로 옮기는 설계" 3번 "산출물의 모양이 다르다,
    그래서 RunProposal에 담지 않는다").

    🔴 2026-09-16 신설 — `draft_type="관계"`(`TYPE_RELATION`)는 새 단계가 아니라
    **3단계 안의 두 번째 LLM 호출**의 산출물이다(docs/planning.md "지식그래프 관계
    라벨링을 3단계의 두 번째 LLM 호출로 옮긴다" 3-1·3-3번). "이슈로 묶어라"와
    "관계를 뽑아라"가 같은 배치를 보는 서로 다른 두 호출이라, `run_job`은
    `job_key="insight"`인 것을 그대로 공유하고 `draft_type`만 갈라 구분한다.

    🔴 `RunProposal`을 늘리지 않고 새로 만든 이유는 선호가 아니라 구조다.
    `RunProposal.news`는 **단수 FK**인데 `Insight`와 `Report`의 근거 기사는 M2M이고,
    그 목록 자체가 산출물의 본체다(출처 기반 작성 원칙. `Insight.news`/`Report.news`에
    연결된 기사가 출처 표기 역할을 겸한다). 단수 FK에 M2M을 담을 방법이 없으므로
    "겸하게 되는 대가를 치를지"가 아니라 "애초에 안 들어간다"이다.

    `RunProposal`과 같은 성질을 상속한다. `run_job` FK로 묶이고, 확정 전까지 DB에
    반영되지 않으며, 채택/거절/취소 상태를 가진다. `status`는 `RunProposal.STATUS_CHOICES`를
    그대로 참조한다(드리프트 방지. `axis`가 `TagCorrectionRecord.AXIS_CHOICES`를
    참조하는 것과 같은 이유).

    🔴 절대 상속하지 않는 것이 있다. **벡터를 달지 않는다.** 나중에 초안 중복 감지가
    필요해져도 검색 대상 벡터(`Embedding`)와 같은 테이블에 넣지 않는다. 한 테이블이면
    조회부가 필터를 빼먹는 순간 초안이 실제 검색 결과에 섞이고, 그것이 이 프로젝트가
    반복한 "어겨도 에러가 안 나는" 실패 유형이다.

    `draft_type`에 따라 쓰지 않는 칸이 생긴다(이슈 초안은 `overview`와 `date_from`,
    `date_to`가 비고, 보고서 초안은 `implication`과 `grade`가 빈다). 공통 칸 둘에
    매핑표를 붙이는 안보다 이쪽을 택한 이유는 `Insight`/`Report`의 필드 이름을 그대로
    쓰면 확정 코드가 옮겨 담는 자리에서 헷갈리지 않기 때문이다(빈 칸 몇 개보다 변환이
    있는 자리가 더 위험하다).
    """

    TYPE_INSIGHT = "이슈"
    TYPE_WEEKLY = "주간 보고서"
    TYPE_MONTHLY = "월간 보고서"
    # 🔴 4번째 draft_type(2026-09-17, docs/planning.md "지식그래프 관계 라벨링을
    # 3단계의 두 번째 LLM 호출로 옮긴다" 3-3번 확정) — 3단계 두 번째 호출(관계
    # 뽑기)의 산출물. `RunProposal`을 늘리지 않고 여기 늘린 이유는 클래스
    # docstring의 판단과 같다 — `RunProposal.news`는 단수 FK인데 관계 하나의
    # 근거는 여러 기사일 수 있다.
    TYPE_RELATION = "관계"
    # 🔴 5번째 draft_type(2026-09-17, docs/planning.md "RA 손 작업을 전부 단계
    # 안으로 넣는다" 2번 확정) — 3단계 세 번째 호출(헤드라인 순위)의 산출물. 확정
    # 대상이 이슈 초안이나 기존 Insight 어느 쪽이든 헤드라인 자리 자체는 이 새
    # draft_type 행 하나로 표현한다 — id(RunDraft.pk)가 확정 POST(headliner_ids)의
    # 값이고, 그 자리가 가리키는 실제 이슈는 headliner_source_draft(이번 배치
    # 초안)나 headliner_source_insight(기존 확정 Insight) 중 정확히 하나로 찾는다.
    TYPE_HEADLINER = "헤드라인"
    TYPE_CHOICES = [
        (TYPE_INSIGHT, "이슈"),
        (TYPE_WEEKLY, "주간 보고서"),
        (TYPE_MONTHLY, "월간 보고서"),
        (TYPE_RELATION, "관계"),
        (TYPE_HEADLINER, "헤드라인"),
    ]

    run_job = models.ForeignKey(RunJob, on_delete=models.CASCADE, related_name="drafts")
    draft_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    title = models.CharField(max_length=500)
    content = models.TextField(
        help_text="Insight.content, Report.content, OrgRelation.description 또는(헤드라인 전용) "
                   "헤드라인 순위 사유(1-A 사슬 결과 한 문장).",
    )
    implication = models.TextField(blank=True, help_text="이슈 전용. Insight.implication.")
    overview = models.TextField(blank=True, help_text="보고서 전용. Report.overview.")
    # 🔴 2026-09-17 신설(docs/planning.md "RA 손 작업을 전부 단계 안으로 넣는다" 3·4번) —
    # 축약본(content_short/implication_short) 문장 번호 배열. LLM이 문자열이 아니라
    # 이 인덱스만 내고, services/llm.py의 build_short_field()가 원문 문장을 그대로
    # 이어 붙여 만든다("삭제만 허용"이 구조로 보장된다). 이슈 초안(TYPE_INSIGHT)과
    # 보고서 초안(TYPE_WEEKLY/TYPE_MONTHLY)만 채운다 — 관계·헤드라인 초안은 축약본
    # 개념이 없다. implication_keep은 이슈 전용이다(보고서엔 implication 필드가 없다).
    content_keep = models.JSONField(default=list, blank=True, help_text="축약본 content_short 문장 번호.")
    implication_keep = models.JSONField(
        default=list, blank=True, help_text="이슈 전용. 축약본 implication_short 문장 번호.",
    )
    # 🔴 자체 상수를 새로 만들지 않고 Insight.GRADE_CHOICES를 그대로 참조한다
    # (RunProposal.axis가 TagCorrectionRecord.AXIS_CHOICES를 참조한 것과 같은 드리프트
    # 방지). 기본값은 빈 문자열이다. Insight.GRADE_UNSPECIFIED("미지정")는 "판정했으나
    # 등급을 못 정했다"는 뜻인 반면, 여기서 빈 문자열은 "이 초안 종류에 등급이라는 개념이
    # 없다"(보고서 초안)는 뜻이라 서로 다르다. 이슈 초안은 프롬프트 조립과 판정 단계에서
    # 반드시 값을 채운다(승격 위계 등급 정책 3번 "RA가 생성 시점에 매긴다, 필수").
    grade = models.CharField(
        max_length=20, choices=Insight.GRADE_CHOICES, blank=True, default="",
        help_text="이슈 전용. Insight.GRADE_CHOICES를 그대로 참조한다.",
    )
    # 🔴 2026-09-15 PE 신설(3단계 라운드) — templates/setting/run_review.html
    # insight_items 계약의 grade_reason. "RunDraft에 이 칸이 없다"는 그 파일의 실측을
    # 이 필드로 메운다. "이유 없는 체크박스 목록은 사람이 검토할 수 없다"는 그 계약의
    # 근거를 그대로 따라 넣는 쪽을 택했다 — grade와 마찬가지로 이슈 초안 전용이다.
    grade_reason = models.TextField(blank=True, help_text="이슈 전용. LLM이 그 등급을 고른 이유.")
    date_from = models.DateField(null=True, blank=True, help_text="보고서 전용.")
    date_to = models.DateField(null=True, blank=True, help_text="보고서 전용.")
    news = models.ManyToManyField(News, related_name="run_drafts", help_text="근거 기사.")
    # 🔴 관계 전용 필드 셋(TYPE_RELATION, docs/planning.md 같은 절 3-2·3-3번).
    # FK인 이유 — 3-2번이 못박은 그대로다. "관계는 미등록 기업을 가리킬 수 없다"
    # (이미 태깅된 기업 중에서만 고르므로 해석 실패가 구조적으로 없다), 그래서
    # `RunProposal.target_name`이 문자열인 근거(해석 실패 가능성)가 여기엔
    # 적용되지 않는다. on_delete=SET_NULL — 기업이 비활성화·삭제돼도 이 초안
    # 행(감사 기록) 자체는 남아야 한다(created_insight·created_report와 같은 근거).
    relation_org_a = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="관계 전용. 관계의 한쪽 기업.",
    )
    relation_org_b = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="관계 전용. 관계의 다른 쪽 기업.",
    )
    # 🔴 max_length=50 — OrgRelation.label과 반드시 같아야 한다. apps/graph/views.py의
    # MAX_LABEL_LENGTH=50이 이미 같은 계약을 코드로 못박고 있고(주석 참고), 어긋나면
    # 확정 시점에 사람이 읽을 수 없는 DataError로 500이 난다(같은 절 3-3번이 지목한
    # 실제 재현 버그와 같은 자리). LLM에게는 enum으로 닫힌 7종
    # (기술협업·공동개발·공급계약·지분투자·인수·업무협약·파트너십, 같은 절 5-(a)) 중
    # 하나가 채워진다 — 이 필드 자체는 자유 문자열이다(엄격한 제약은 프롬프트
    # 출력 검증이 진다, services/runner.py 몫).
    relation_label = models.CharField(
        max_length=50, blank=True, default="",
        help_text="관계 전용. 7종 어휘(기술협업/공동개발/공급계약/지분투자/인수/업무협약/파트너십) 중 하나.",
    )

    # 🔴 헤드라인 전용 필드 셋(TYPE_HEADLINER, docs/planning.md "RA 손 작업을 전부
    # 단계 안으로 넣는다" 2번). content 필드가 순위 사유를 담는다(위 content 필드
    # 정의 참고) — 여기는 그 사유가 설명하지 못하는 자리(순위·업권·교체 이력·근거
    # 이슈 연결)만 담는다.
    headliner_rank = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="헤드라인 전용. 1~3(2-4 상한 3).",
    )
    # 🔴 업권을 DB 필드로 만들지 않는다는 5-1 조항은 Insight/Organization에 대한
    # 것이다 — 여기는 그 판정 자체가 아니라 검토 화면이 배지로 보여줄 라벨을
    # 잠깐 담아 두는 자리이고, 확정해도 Insight에 저장되지 않는다(2-1).
    headliner_sector = models.CharField(
        max_length=50, blank=True, default="", help_text="헤드라인 전용. 5-1 업권 라벨. Insight에 저장하지 않는다.",
    )
    headliner_sector_unlisted = models.BooleanField(
        default=False, help_text="헤드라인 전용. 5-1 업권 목록에 없는 라벨이면 True.",
    )
    HEADLINER_CHANGE_NEW = "new"
    HEADLINER_CHANGE_MOVED = "moved"
    HEADLINER_CHANGE_SAME = "same"
    HEADLINER_CHANGE_CHOICES = [
        (HEADLINER_CHANGE_NEW, "신규"),
        (HEADLINER_CHANGE_MOVED, "직전 순위에서 이동"),
        (HEADLINER_CHANGE_SAME, "유지"),
    ]
    headliner_change = models.CharField(
        max_length=10, choices=HEADLINER_CHANGE_CHOICES, blank=True, default="",
        help_text="헤드라인 전용. 직전 지정과 견준 결과(5-2).",
    )
    headliner_prev_rank = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="헤드라인 전용. headliner_change='moved'일 때만.",
    )
    headliner_change_reason = models.TextField(
        blank=True, default="",
        help_text="헤드라인 전용. 교체 사유(5-2). 창 밖 이탈·중복 제외·다양성은 코드가, 그 "
                   "밖의 재적용은 LLM이 채운다.",
    )
    # 이 헤드라인 후보가 가리키는 실제 이슈 — 이번 배치 초안(이슈로 아직 Insight가 아님)
    # 또는 창 안 기존 확정 Insight 중 정확히 하나만 채운다(2-2). 확정 뷰가 여기서
    # Insight.headliner_order를 채울 대상을 찾는다.
    headliner_source_draft = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="헤드라인 전용. 이번 배치 이슈 초안(RunDraft, TYPE_INSIGHT)이 후보면 그 pk.",
    )
    headliner_source_insight = models.ForeignKey(
        Insight, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="헤드라인 전용. 창 안 기존 확정 Insight가 후보면 그 pk(from_existing).",
    )
    status = models.CharField(
        max_length=10, choices=RunProposal.STATUS_CHOICES, default=RunProposal.STATUS_PENDING,
    )
    # 확정으로 만들어진 대상이다. 되돌릴 때 무엇을 지울지 아는 자리(draft_type별로 정확히
    # 하나만 채워진다). GenericForeignKey 대신 별도 FK 둘로 가른 이유는 위 클래스
    # docstring의 content/implication/overview 판단과 같다. 이 코드베이스에
    # GenericForeignKey 선례가 없고, 타입이 갈리는 변환 지점을 새로 만들지 않는다.
    # on_delete는 SET_NULL이다. RunProposal.news와 같은 근거로, 되돌리기(확정된
    # Insight/Report를 지움)가 일어나도 RunDraft 행 자체(감사 기록)는 남아야 한다.
    created_insight = models.ForeignKey(
        Insight, on_delete=models.SET_NULL, null=True, blank=True, related_name="run_drafts",
    )
    created_report = models.ForeignKey(
        Report, on_delete=models.SET_NULL, null=True, blank=True, related_name="run_drafts",
    )
    # 🔴 네 번째 "확정으로 만들어진 대상" FK(관계 전용, 같은 절 3-3번). 기존 둘과
    # 같은 근거 — 되돌리기(확정된 OrgRelation을 지움)가 일어나도 이 RunDraft 행은
    # 남아야 한다.
    created_relation = models.ForeignKey(
        OrgRelation, on_delete=models.SET_NULL, null=True, blank=True, related_name="run_drafts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"RunDraft({self.draft_type}, {self.title})"
