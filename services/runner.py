"""SET-010 실행 뼈대 — 워커 스레드와 manage.py 명령이 함께 쓰는 단일 실행 로직
(docs/planning.md "1번을 LLM으로 옮기는 설계" 3번 "실행 모델").

🔴 로직은 여기 한 벌만 둔다. apps/setting/views.py의 setting_run_start()와
apps/setting/management/commands/run_job.py는 둘 다 이 모듈의 start_run()/run_now()를
부른다 — 두 벌이 되면 어느 쪽으로 돌렸느냐에 따라 처리량이 갈리기 시작한다(같은 문서
3-(f)).

새 인프라(Celery·Redis)는 들이지 않는다(같은 문서 3-(a)). Django 프로세스 안 워커
스레드로 돌리고, 상태는 전부 RunJob(DB)에 쓴다 — 메모리에 두지 않는다(3-(c)). gunicorn
워커가 여럿이면 스레드가 뜬 워커와 폴링이 오는 워커가 다를 수 있어, 전역 변수로 진행
상황을 들고 있으면 폴링이 그것을 못 본다.
"""

import hashlib
import logging
import re
import threading
import time
from datetime import timedelta

from django.db import IntegrityError, connection, transaction
from django.db.models import F, Max
from django.utils import timezone

from apps.setting.models import CollectionLog, Keyword, RunJob

logger = logging.getLogger(__name__)

# 화면·manage.py run_job 명령이 실제로 열어 두는 job_key만 여기 나열한다. 관리 명령의
# choices가 이 목록 하나를 본다.
#
# 🔴 "cleanup"은 2026-09-14 2라운드에서 _run_cleanup()이 구현됐고, 이번(검토 화면 +
# 확정 뷰) 라운드에서 apps/setting/views.py의 setting_run_start()가 "cleanup" 분기를
# 얻어 버튼이 실제로 열렸다 — 그래서 여기 함께 넣는다. 확정 경로(휴먼 인 더 루프) 없이
# 버튼만 열면 사람이 판정을 쌓아 놓고 확정할 자리가 없어지므로, 검토 화면과 확정 뷰가
# 먼저 갖춰진 뒤에 이 목록에 추가한 것이다.
#
# 🔴 "insight"는 2026-09-15 라운드에서 함께 연다. _run_insight()와 검토 화면(insight
# 초안 확정 경로)은 이미 지난 라운드에 갖춰져 있었고, 이번 라운드는 버튼 자체
# (apps/setting/views.py setting_run_start()의 "insight" 분기와 _research_jobs_context()의
# can_run)와 선행 잠금(_insight_block_reason())을 함께 연다.
#
# 🔴 "weekly"·"monthly"는 같은 날 뒤이은 라운드에서 연다(4, 5단계). _run_report()가
# insight와 같은 구조(배치 전체 1호출, 이어하기 없음)를 그대로 쓰되 대상이 News가
# 아니라 Insight다 — services/report_periods.py가 정본으로 계산한 대상 기간의 Insight를
# 읽는다.
#
# 🔴 "newsroom_filter"는 뒤이은 라운드(교보 소식 축 2단계)에서 연다(docs/planning.md
# "뉴스룸" 절 12-2, 12-5 PE 인계 2번). insight/weekly/monthly와 같은 구조(배치 전체
# 1호출)이지만 휴먼 인 더 루프가 없다 — 판정 결과를 RunProposal 같은 중간 그릇 없이
# NewsroomArticle에 바로 쓴다(12-2 (b)(c)). apps/setting/views.py의
# setting_run_start()가 "newsroom_filter" 분기와 버튼(can_run = pending_count > 0)을
# 함께 연다.
#
# 🔴 "newsroom_compose"는 같은 날 뒤이은 라운드(교보 소식 축 3단계)에서 연다
# (docs/planning.md "뉴스룸" 절 12-3, 12-5 PE 인계 6~7번). newsroom_filter와 같은
# 것 셋(배치 전체 1호출, 휴먼 인 더 루프 없음, 판정 기준 원문을 코드가 아니라
# Newsroom.compose_prompt에서 읽는다) — 다른 것은 대상이 NewsroomArticle이 아니라
# 새 모델 NewsroomMessage(발송 레코드) 1건이라는 점이다(12-3 (b)).
IMPLEMENTED_JOB_KEYS = (
    "collect", "newsroom_collect", "cleanup", "insight", "weekly", "monthly",
    "newsroom_filter", "newsroom_compose",
)

# 하트비트 정지 판정 임계값(초). 별도 감시 프로세스 없이, 화면을 읽는 요청마다
# mark_stale_running_as_stopped()가 이 값으로 "진행중인데 멈춘 것"을 가려낸다
# (docs/planning.md 3-(e) "임계 시간은 PE가 실측으로 정한다").
#
# 🔴 실측 근거(2026-09-14, 로컬, Django test Client로 실제 버튼 경로를 그대로 타서
# 측정) — SET-010 "1단계 수집"을 실제로 실행해 RunJob 하트비트 간격(키워드 1개
# 처리마다 한 번, 19개 활성 키워드)을 쟀다.
#   - 실측된 간격 19개: 0.5~3.52초, 최댓값 3.52초
#   - 전체 수집(19개 키워드, 68건 신규 수집) 총 소요: 약 34초
# 이 값 그대로는 쓰지 않는다 — 오늘 수집이 유독 빨랐을 수 있어(크롤 대상 매체가
# 대부분 응답이 빨랐던 날일 수 있음) 실측 최댓값에 딱 붙이면 다음 실행이 조금만
# 느려져도 오판한다. 코드 상 이론적 상한도 함께 본다 — 키워드당 최대
# NAVER_DISPLAY_PER_QUERY(.env=10)건, 건마다 최대 2회 순차 크롤 시도
# (services/crawler.py fetch_article_body: 네이버 본문 시도 TIMEOUT=8초 +
# trafilatura 시도)이므로 한 키워드가 전부 타임아웃에 걸리는 최악의 경우 수 분대까지
# 늘어날 수 있다. 실측(초 단위)과 이 이론적 상한(분 단위) 사이에서, "진짜 죽은
# 프로세스"를 상식적인 시간 안에 잡아내면서도 평범한 지연(느린 매체 몇 곳)을
# 오판하지 않을 값으로 180초(3분)를 택했다 — 실측 최댓값의 약 50배 여유이자, 흔한
# 헬스체크 타임아웃 관례(수 분)와도 맞았다.
#
# 🔴 2026-09-17 재실측 — 180초가 실제로 오판을 냈다(RunJob pk150). 그날 9개
# 키워드를 39초(키워드당 평균 4.3초)에 처리하다가 10번째 키워드 하나에서 최소
# 185초를 넘겨 "죽은 것"으로 판정돼 중단됐다. 사용자는 중단 버튼을 누르지 않았다
# (stop_requested_at이 비어 있었다) — 실제로는 크롤이 느렸을 뿐 죽지 않았다.
#
# 다른 collect/newsroom_collect 실행의 키워드당 평균(RunJob.target_count로 나눈
# 값)은 1.13~9.19초로 전부 이 사고의 24.98초(pk150, 9개 완료분 평균)보다도
# 훨씬 낮았다 — 이번 지연이 얼마나 예외적이었는지 보여 준다.
#
# 🔴 근본 처방은 위 on_heartbeat다(services/collector.py collect_naver() 참고) —
# 하트비트를 키워드 단위가 아니라 **기사 단위**로 올리게 했다. 그러면 한 키워드
# 안에서 값이 오래 안 올라가는 간격이 "느린 기사 1건이 걸리는 시간"(최악
# 8+30+8=46초, 크롤 세 단계 타임아웃의 합)으로 줄어든다. 이 값(180초)은 그
# 처방이 실패했을 때(정말로 프로세스가 죽었을 때)를 잡는 안전판이라, 처방
# 이후에도 그대로 두면 안 된다 — 46초짜리 정상 지연에 여유를 주지 않으면
# 이번과 같은 오판이 다시 난다.
#
# 300초(5분)를 택한다 — 위 46초 이론적 상한의 약 6.5배 여유(종전 180초가 종전
# 이론적 상한 3.52초에 약 50배 여유를 뒀던 것과 같은 종류의 안전판이다), 실측
# 정상 범위(1~9초/키워드)의 약 33~270배라 평범한 지연을 절대 죽이지 않으면서도,
# 배치 1호출 단계의 900초(아래)보다는 짧게 유지해 "건별 단계가 더 빨리 잡혀야
# 한다"는 구분이 무너지지 않는다.
HEARTBEAT_STALE_SECONDS = 300

# 🔴 3~5단계(주요 이슈, 주간 보고서, 월간 보고서) 전용 임계값(docs/planning.md
# "3~5단계를 LLM으로 옮기는 설계" 9-(b)). 위 300초는 "건별 진행 간격"(기사 1건마다
# 하트비트를 찍는 collect·newsroom_collect·cleanup)의 실측으로 잡은 값인데, 3~5단계는
# 배치 전체를 한 호출에 담아(같은 문서 7-(a)) **호출 하나가 통째로 걸리는 시간**이 그
# 간격이다. 시작할 때 한 번 하트비트를 찍고 그 호출이 끝날 때까지 다시 찍을 자리가
# 없으므로, 300초를 그대로 쓰면 호출이 5분을 넘기는 순간 살아있는 실행을 중단됨으로
# 오판한다. 🔴 2026-09-17 재확인 — 300초와 900초(3배)로 갈리는 구분 자체는 여전히
# 유효하다(건별은 기사 1건 단위, 배치는 호출 전체 단위라는 서로 다른 근거 위에 있고,
# 위 재실측이 건별 쪽 값만 바꿨다). 배치 쪽 900초는 아직 실측이 없다는 사실도
# 그대로다(아래 문단).
#
# ⚠️ 3단계가 아직 구현되지 않아(services/llm.py에 3~5단계 함수가 없다) 실측이
# 불가능하다. 그래서 실측이 아니라 **근거 있는 추정**이다. 첫 실행 후 PE가 실제
# 소요 시간으로 이 값을 교체한다(문서 9-(b) "값은 확인 필요다. PE가 첫 실행에서
# 재고 정한다").
#
# 추정 근거: services/llm.py classify_news()가 쓰는 AnthropicBedrock 클라이언트는
# 요청 하나당 기본 타임아웃이 10분(600초)이고(claude-api 스킬 "Client config" 문서.
# Python과 Ruby는 초 단위, 기본 10분), SDK 기본 재시도(max_retries=2)가 타임아웃에도
# 걸리므로 이론상 최악은 600초를 세 번(첫 시도 더하기 재시도 두 번) 반복한 1,800초까지
# 늘어날 수 있다(같은 문서 "Timeouts are retried, wall-clock can reach timeout times
# max_retries plus 1"). 그 최악값을 그대로 쓰면 실제로 죽은 스레드도 30분 동안
# "진행중"으로 남아 전역 실행 잠금(RunJob.Meta.unique_running_run_job)을 그만큼 오래
# 붙잡는다. 그 대가가 크다고 보고, 첫 시도(600초)에 재시도 한 번의 여유(300초)만 더한
# 900초(15분)를 잠정값으로 둔다. 그 이상 길어지는 재시도는 "진짜 죽은 프로세스"로
# 보고 중단됨 처리해 잠금을 푼다.
HEARTBEAT_STALE_SECONDS_BY_JOB_KEY = {
    "insight": 900,
    "weekly": 900,
    "monthly": 900,
    # 🔴 "newsroom_filter"도 배치 전체 1호출이라 같은 임계값을 쓴다(교보 배치는
    # 하루 20건 안팎으로 insight/weekly/monthly보다 입력이 작아 실제로는 더 짧게
    # 끝날 가능성이 높지만, 아직 실측이 없어 같은 근거 있는 추정을 그대로 쓴다).
    # 첫 실행 후 PE가 실제 소요 시간으로 교체한다(위 주석과 같은 절차).
    "newsroom_filter": 900,
    # 🔴 "newsroom_compose"도 같은 이유(배치 전체 1호출)로 같은 임계값을 쓴다.
    # 입력이 판정 전량이 아니라 그중 통과분(대개 더 작다)이라 filter보다도 짧게
    # 끝날 가능성이 높지만, 아직 실측이 없다.
    "newsroom_compose": 900,
}


def mark_stale_running_as_stopped() -> int:
    """하트비트가 끊긴 지 오래된 진행중 RunJob을 중단됨으로 표시한다. 감시 프로세스를
    따로 두지 않고, 화면을 읽는 요청(apps/setting/views.py의 setting_run() 등)마다
    이 함수를 호출해 그 자리에서 판정한다(문서 3-(e)). 반환값은 중단됨으로 바뀐 건수.

    🔴 job_key별로 임계값이 갈리므로(위 HEARTBEAT_STALE_SECONDS_BY_JOB_KEY) 단일
    UPDATE 한 번으로 끝내던 종전 구조를 "특수 job_key마다 한 번, 나머지 한 번"으로
    바꿨다. 쿼리가 늘지만 비용은 무시할 만하다. RunJob.Meta.unique_running_run_job이
    "진행중" 행을 시스템 전체에 최대 1개로 강제하므로, 이 함수가 실제로 갱신 대상으로
    보는 행은 항상 0개 아니면 1개다.

    🔴 2026-09-15 PE 개정 — finished_at도 함께 찍는다(종전에는 status만 바꾸고
    finished_at을 비워 뒀다). apps/setting/views.py의 SET-010 노드 배지가 "오늘
    벌어진 중단"을 판정할 때 finished_at을 본다(docs/planning.md "SET-010 노드
    배지" 3번) — 비워 두면 중단된 배치는 날짜를 영영 알 수 없어 그 판정이
    불가능해진다."""
    now = timezone.now()
    stopped = 0
    special_keys = list(HEARTBEAT_STALE_SECONDS_BY_JOB_KEY.keys())
    for job_key, seconds in HEARTBEAT_STALE_SECONDS_BY_JOB_KEY.items():
        threshold = now - timedelta(seconds=seconds)
        stopped += RunJob.objects.filter(
            job_key=job_key, status=RunJob.STATUS_RUNNING, heartbeat_at__lt=threshold,
        ).update(status=RunJob.STATUS_STOPPED, finished_at=now)
    default_threshold = now - timedelta(seconds=HEARTBEAT_STALE_SECONDS)
    stopped += RunJob.objects.exclude(job_key__in=special_keys).filter(
        status=RunJob.STATUS_RUNNING, heartbeat_at__lt=default_threshold,
    ).update(status=RunJob.STATUS_STOPPED, finished_at=now)
    return stopped


def _create_running_job(job_key: str, actor: str) -> RunJob | None:
    """RunJob을 진행중 상태로 만든다. 이미 다른 RunJob이 진행중이면(전역 잠금,
    RunJob.Meta.constraints) IntegrityError를 잡아 None을 반환한다 — 화면의 can_run
    차단은 사람이 두 번 누르는 것만 막고 경합 자체는 못 막으므로 DB 제약이 진짜
    방어선이다(문서 3-(g))."""
    now = timezone.now()
    try:
        with transaction.atomic():
            return RunJob.objects.create(
                job_key=job_key, actor=actor,
                status=RunJob.STATUS_RUNNING,
                started_at=now, heartbeat_at=now,
            )
    except IntegrityError:
        return None


def start_run(job_key: str, actor: str, **kwargs) -> RunJob | None:
    """RunJob을 만들고 워커 스레드를 띄운 뒤 즉시 반환한다(요청 타임아웃에 걸리지
    않는 이유, 문서 3-(d)). 이미 같은 종류든 다른 종류든 무언가 진행중이면 RunJob을
    만들지 않고 None을 반환한다."""
    mark_stale_running_as_stopped()
    run_job = _create_running_job(job_key, actor)
    if run_job is None:
        return None
    thread = threading.Thread(target=_execute, args=(run_job.pk, kwargs), daemon=True)
    thread.start()
    return run_job


def run_now(job_key: str, actor: str, **kwargs) -> RunJob | None:
    """관리 명령 전용 — 같은 실행 로직을 현재 스레드에서 끝까지 블로킹으로 돌린다
    (문서 3-(f) "웹 요청 없이 테스트와 재현이 가능해야 한다"). 반환된 RunJob은 이미
    끝난 뒤의 최종 상태를 담고 있다."""
    mark_stale_running_as_stopped()
    run_job = _create_running_job(job_key, actor)
    if run_job is None:
        return None
    _execute(run_job.pk, kwargs)
    return RunJob.objects.get(pk=run_job.pk)


def _stop_requested(run_job_id: int) -> bool:
    """SET-010 실행 중단(docs/planning.md 「SET-010 실행 중단」 0번, 9-3) — 지금
    중단 요청이 들어와 있는지 DB에서 직접 다시 읽는다. 워커 스레드가 들고 있는
    RunJob 인스턴스에는 다른 요청이 적은 stop_requested_at이 반영되지 않으므로
    (서버가 재시작되면 스레드 자체가 죽는다), 루프 안에서 매 건마다 이 함수로
    다시 조회해야 한다."""
    return RunJob.objects.filter(pk=run_job_id, stop_requested_at__isnull=False).exists()


def _progress_callback(run_job_id: int):
    """건(이번 라운드는 키워드) 하나 처리를 마칠 때마다 부를 콜백을 만든다.
    RunJob.objects.filter(...).update()로 쓴다 — 인스턴스를 불러 save()하지 않는 이유는
    폴링·다른 갱신과 겹쳐도 F() 표현식이 원자적으로 증가시켜 경합에 안전하기 때문이다."""
    def on_progress():
        RunJob.objects.filter(pk=run_job_id).update(
            processed_count=F("processed_count") + 1,
            heartbeat_at=timezone.now(),
        )
    return on_progress


# 🔴 2026-09-17 신설(오늘 실측 사고, RunJob pk150) — 기사 한 건을 살필 때마다 불러도
# 되는 하트비트 전용 콜백. _progress_callback()과 다른 자리다 — 그쪽은 "건(키워드)
# 하나 끝"에서 processed_count까지 함께 올리지만, 여기는 "기사 한 건을 살피기
# 시작"할 때마다 하트비트만 올린다(services/collector.py collect_naver()의
# on_heartbeat 계약).
#
# min_interval로 스로틀한다 — 기사 10건짜리 키워드라도 실제 DB 쓰기는 최대
# HEARTBEAT_MIN_INTERVAL_SECONDS마다 한 번이다. 클로저 안에 마지막으로 쓴 시각을
# 들고 있다가 그 간격 안이면 조용히 넘어간다. time.monotonic()을 쓰는 이유는
# 시스템 시계가 도중에 바뀌어도(예: NTP 보정) 흐르지 않거나 거꾸로 가지 않는
# 시계이기 때문이다 — timezone.now()는 DB에 쓸 값을 만들 때만 쓴다.
HEARTBEAT_MIN_INTERVAL_SECONDS = 5.0


def _heartbeat_callback(run_job_id: int, min_interval: float = HEARTBEAT_MIN_INTERVAL_SECONDS):
    # 🔴 sentinel은 0.0이 아니라 None이다 — time.monotonic()의 기준점은 임의라
    # 프로세스 갓 시작 직후처럼 실제로 작은 값을 돌려줄 수도 있다. 0.0을 "아직
    # 안 썼다"의 표식으로 쓰면 그런 드문 경우 첫 호출이 스로틀에 걸려 최초
    # 하트비트가 min_interval만큼 늦게 찍힌다 — None이면 그 경우가 아예 없다.
    last_written = {"at": None}

    def on_heartbeat():
        now = time.monotonic()
        if last_written["at"] is not None and now - last_written["at"] < min_interval:
            return
        last_written["at"] = now
        RunJob.objects.filter(pk=run_job_id).update(heartbeat_at=timezone.now())
    return on_heartbeat


def _run_collect(run_job_id: int, actor: str) -> None:
    from services.collector import run_collection

    target = Keyword.objects.filter(keyword_type=Keyword.TYPE_COLLECT, is_active=True).count()
    RunJob.objects.filter(pk=run_job_id).update(target_count=target)

    # run_collection()의 actor는 CollectionLog.actor 값(수동(화면)/자동(스케줄))이라
    # RunJob.actor(화면/관리 명령)와 어휘가 다르다 — 스케줄이 폐기된 지금 이 실행기를
    # 거치는 모든 수집은 사람이 시킨 것이므로 기존 화면 버튼과 동일하게 ACTOR_MANUAL로
    # 남긴다. actor 인자를 그대로 두 번째 CollectionLog.actor 값으로 승격시키지 않는다
    # — 새 choices 값을 만드는 건 이번 라운드 범위 밖이다.
    # 🔴 23차 개정 — should_stop이 「지금 하고 있는 키워드 한 개가 끝나면 멈춘다」는
    # 계약을 만든다. collect_naver()가 키워드 하나를 다 처리한 자리(on_progress를
    # 부른 바로 다음)에서만 이 콜백을 확인한다.
    # 🔴 2026-09-17 신설 — on_heartbeat는 그보다 훨씬 자주(기사 한 건마다) 불려
    # 한 키워드 안에서 느린 크롤이 이어져도 하트비트가 오래 안 멈춘다(오늘 실측
    # 사고, RunJob pk150 — 위 HEARTBEAT_STALE_SECONDS 주석 참고).
    run_collection(
        actor=CollectionLog.ACTOR_MANUAL, on_progress=_progress_callback(run_job_id),
        should_stop=lambda: _stop_requested(run_job_id),
        on_heartbeat=_heartbeat_callback(run_job_id),
    )


def _save_proposals(run_job_id: int, news, result: dict) -> None:
    """판정 결과 dict(services/llm.py classify_news()의 반환값)를 RunProposal 행으로
    저장한다. 한 트랜잭션으로 묶되, 건별 판정 자체가 이미 건별 커밋 단위다(설계
    8-(a) "전부 돌고 한꺼번에 저장하지 않는다") — 여기서 만드는 여러 행(유지/삭제 1개
    + 태그 제안 N개)은 그 한 건에 딸린 하나의 판정 결과이므로 함께 묶는다.

    🔴 행은 태그마다 하나다(설계 4-(b)) — tag_corrections·tag_candidates의 원소 각각이
    별도 RunProposal 행이 된다.

    🔴 2026-09-15 개정 — `unregistered_org_candidates`(기업 전용)가 `tag_candidates`(축
    일반화, services/llm.py 참고)로 바뀌었다. 각 원소가 axis("organization"/
    "tech_topic")를 직접 들고 있어 여기서 그대로 RunProposal.axis에 옮긴다 — 종전에는
    기업 전용이라 axis를 비워 뒀지만, 이제는 태그 제거/추가와 같은 방식으로 채운다."""
    from apps.setting.models import RunProposal

    with transaction.atomic():
        proposal_type = (
            RunProposal.TYPE_DELETE if result["relevance"] == "delete" else RunProposal.TYPE_KEEP
        )
        RunProposal.objects.create(
            run_job_id=run_job_id, news=news, proposal_type=proposal_type,
            criterion_code=result.get("criterion_code", ""), reason=result.get("reason", ""),
        )
        for tag in result.get("tag_corrections", []):
            proposal_type = (
                RunProposal.TYPE_TAG_ADD if tag["action"] == "add" else RunProposal.TYPE_TAG_REMOVE
            )
            RunProposal.objects.create(
                run_job_id=run_job_id, news=news, proposal_type=proposal_type,
                target_name=tag["target_name"], axis=tag["axis"], reason=tag.get("reason", ""),
            )
        for candidate in result.get("tag_candidates", []):
            RunProposal.objects.create(
                run_job_id=run_job_id, news=news, proposal_type=RunProposal.TYPE_TAG_CANDIDATE,
                target_name=candidate["name"], axis=candidate["axis"],
                reason=candidate.get("reason", ""),
            )


# 구조적 실패(인증·리전·모델 ID 오류) 감지 임계값(설계 8-(d)) — 이 값만큼 연속으로
# 실패하면 RunJob을 즉시 실패로 끊는다. 개별 건 실패(rate limit·네트워크 일시 오류·
# 응답 형식 불량 등)와 구조적 실패를 예외 타입만으로 완전히 가르지 않고 "연속 횟수"로
# 감지하는 이유는, 400으로만 떨어지는 설정 오류처럼 타입으로는 안 걸러지는 구조적
# 실패도 있기 때문이다(설계 원문이 그대로 이 방식을 지시한다). 3으로 잡은 근거 —
# SDK가 rate limit·5xx·네트워크 오류를 이미 최대 2회 자동 재시도하므로, 그러고도
# 실패가 반복되면 일시적 문제가 아닐 가능성이 높다.
CLEANUP_STRUCTURAL_FAILURE_THRESHOLD = 3


def cleanup_ab_split():
    """SET-010 2단계(뉴스 정리) 판정 상태 두 수 — 이 저장소에서 A/B를 세는
    유일한 정본이다(docs/planning.md "SET-010 검토 단위" 절, 2026-09-16 확정 —
    "A와 B를 세는 함수를 하나만 만들고, 배지·버튼·적체 줄·검토 화면·3단계 선행
    잠금이 전부 그것만 보게 하라"는 지시). apps/setting/views.py가 배지·버튼·
    적체 줄·검토 화면에서 이 함수를 그대로 불러 쓴다 — 대상 쿼리(아래
    _run_cleanup())도 같은 함수를 쓰므로 "무엇이 실행 대상인가"와 "무엇이
    버튼을 여는가"가 절대 갈리지 않는다.

    A(확정 대기) = 미검증 News 중 대기(PENDING) 제안이 있는 것.
    B(미판정)   = 미검증 News 중 대기 제안이 없는 것 — 🔴 실패한 건이 여기
    들어온다(_save_proposals()는 판정이 성공했을 때만 불린다. 실패한 기사는
    제안 자체가 안 생기므로 정의상 B다).

    A + B = 미검증 News 전체다. 날짜를 보지 않는다. 반환값은
    (a_queryset, b_queryset) — .count()나 .exists()를 호출부가 그대로 쓴다.

    RunProposal 쪽은 run_job.status를 보지 않는다 — 연속 3회 실패로 배치가
    STATUS_FAILED로 끊겨도 그 전까지 성공한 판정의 제안은 여전히 유효한 A다
    (RUNNING만 실질적으로 걸러진다 — 진행 중인 배치가 방금 막 저장한 제안이
    있어도, 배지 판정은 RUNNING을 A/B보다 먼저 본다는 우선순위로 자연히
    가려진다)."""
    from apps.news.models import News

    proposed_news_ids = _cleanup_proposed_news_ids()
    unverified = News.objects.filter(status=News.STATUS_UNVERIFIED)
    return unverified.filter(pk__in=proposed_news_ids), unverified.exclude(pk__in=proposed_news_ids)


def _cleanup_proposed_news_ids():
    """cleanup_ab_split()과 cleanup_today_flow()가 같이 쓰는 서브쿼리 — 대기
    (PENDING) 상태인 cleanup RunProposal이 가리키는 news_id 목록. 한 곳에 두는
    이유는 "제안이 있다"의 정의가 두 함수에서 갈리면 A/B와 흐름 줄의 "검토"
    갈래 수가 어긋나기 때문이다."""
    from apps.setting.models import RunProposal

    return RunProposal.objects.filter(
        run_job__job_key="cleanup", status=RunProposal.STATUS_PENDING, news__isnull=False,
    ).values("news_id")


def cleanup_today_flow():
    """SET-010 2단계 노드의 흐름 줄(PD 20차 개정 ② flow) — 오늘 수집된 News가
    지금 어디에 있는지 네 갈래로 센다. docs/design.md "SET-010 · 실행" 20차
    개정 ⑨번 PE 인계가 정본이다.

    🔴 2026-09-17 재정정(오늘 실측 사고) — 모수(오늘 수집 건수)를
    CollectionLog.collected_count 합계로 재는 종전 방식을 걷어낸다. 그 값은
    run_collection()이 **수집 호출이 끝나야만** 1건 기록하는데, 그날 아침 수집이
    하트비트 오판으로 죽었을 때(위 HEARTBEAT_STALE_SECONDS 사고) 워커 스레드가
    services/collector.py collect_naver() 안에 갇힌 채 끝내 돌아오지 못해
    CollectionLog가 **한 건도** 안 남았다(실측: News 40건이 오늘 날짜로 이미
    만들어져 있는데 오늘 CollectionLog는 0건). cleanup_today_flow()가 그 상태를
    "오늘 수집 0건"으로 읽어 흐름 줄 자체가 사라졌고, 그 40건이 전부 backlog의
    "이전 N건"으로 잘못 넘어갔다(_cleanup_backlog() 참고).

    🔴 대신 News.collected_at과 DeletedNewsRecord.collected_at을 함께 센다.
    News 행은 collect_naver()가 기사를 저장하는 그 순간 생기므로(수집 호출이
    끝나기를 기다리지 않는다) 실행이 중단되든 유령 스레드로 걸려 있든 이미
    들어온 기사는 즉시 잡힌다. 삭제된 기사가 모수에서 빠지는 문제(과거에
    CollectionLog를 쓴 이유)는 DeletedNewsRecord로 메운다 —
    delete_news_with_record()가 삭제 직전 News.collected_at을 그대로 복사해
    두므로(apps/news/services.py), 하드 삭제(apps/news/services.py의
    news.delete() 한 곳뿐 — News를 지우는 다른 경로가 저장소에 없다) 뒤에도
    "오늘 수집이었다"는 사실이 남는다.

    🔴 삭제 건수는 여전히 직접 쿼리하지 않고 뺄셈으로 구한다 — 다만 이제는 그
    뺄셈이 항상 DeletedNewsRecord의 실제 오늘 수집분 건수와 정확히 같아진다
    (모수 자체가 "현재 News" + "DeletedNewsRecord"의 합이므로). "모수 − (지금
    남아 있는 오늘 수집분)"으로 구하면 네 갈래의 합이 모수와 같아지는 것이
    산술적으로 보장되는 구조는 그대로다 — 별도의 무결성 검사가 필요 없다.

    반환값은 dict {"total", "deleted", "verified", "review", "waiting"} 또는
    오늘 수집이 0건이면 None(그날은 "오늘 흐름"이 없는 것이 사실이라 줄 자체를
    내리지 않는다, 20차 ④번)."""
    from django.utils import timezone

    from apps.news.models import DeletedNewsRecord, News

    today = timezone.localtime(timezone.now()).date()
    today_news = News.objects.filter(collected_at__date=today)
    today_deleted_count = DeletedNewsRecord.objects.filter(collected_at__date=today).count()
    verified = today_news.filter(status=News.STATUS_VERIFIED).count()
    unverified_today = today_news.filter(status=News.STATUS_UNVERIFIED)
    proposed_ids = _cleanup_proposed_news_ids()
    review = unverified_today.filter(pk__in=proposed_ids).count()
    waiting = unverified_today.exclude(pk__in=proposed_ids).count()
    total = verified + review + waiting + today_deleted_count
    if total == 0:
        return None

    # 🔴 뺄셈 — 위 docstring 참고. max(..., 0)은 방어적 하한선이다(정상 경로에서는
    # 항상 today_deleted_count와 같지만, 실행 도중 폴링이 걸리는 등 순간적인
    # 불일치까지 완전히 배제하지는 않는다).
    deleted = max(total - (verified + review + waiting), 0)
    return {"total": total, "deleted": deleted, "verified": verified, "review": review, "waiting": waiting}


def insight_ab_split():
    """SET-010 3단계(주요 이슈) 배정 두 수 — 위 cleanup_ab_split()과 같은 이유로
    정본을 하나만 둔다(docs/planning.md "SET-010 검토 단위" 절 11번, PD 19차
    개정 ③번 표). 분자(배정)=탈락 표식 없는 검증 News 중 이미 어느 Insight에
    묶인 것, 분모는 그 전체(묶였든 아직 안 묶였든, 탈락 표식만 없으면 된다).
    _run_insight()의 대상 쿼리(insights__isnull=True인 쪽)와 글자 그대로 같은
    후보 집합이라 배지·적체 줄·선행 잠금·실행 대상이 어긋나지 않는다.

    반환값은 (assigned_queryset, unassigned_queryset). 🔴 둘 다 distinct-safe
    쿼리셋이다 — 호출부가 .count()/.exists()를 그대로 불러도 안전하다(2026-09-16
    실측 사고 정정, 아래 참고).

    🔴 실측 버그 — `candidates.filter(insights__isnull=False)`는 Insight
    M2M을 직접 JOIN한다. 기사 한 건이 이슈 두 개에 묶여 있으면 그 JOIN이 행을
    둘로 늘려 count()가 241을 냈는데(distinct하면 230), 실제로는 검증된 뉴스
    247건 중 230건이 배정이었다(230 + 17 = 247, 미배정 쪽은 애초에 JOIN이
    NULL 한 행만 남겨 늘지 않았다 — 17=17로 실측 일치). `unassigned`(위 표의
    B에 해당)는 `insights__isnull=True`라 원래도 늘지 않지만, 대칭을 맞추고
    "이 함수가 반환하는 쿼리셋은 항상 distinct-safe"라는 불변식을 지키기 위해
    같은 방식(서브쿼리)으로 통일한다 — `.distinct()`를 이 함수 밖에서 붙이는
    방식은 호출부 하나라도 빠뜨리면 같은 사고가 재발한다(코디네이터 지시)."""
    from apps.news.models import News

    candidates = News.objects.verified().filter(insight_dismissed_at__isnull=True)
    # 🔴 cleanup_ab_split()과 같은 서브쿼리 패턴 — pk__in은 SQL의 IN절이라
    # 서브쿼리 안에 중복 행이 있어도 바깥 쿼리를 늘리지 않는다(JOIN처럼 행을
    # 곱하지 않는다). distinct() 대신 이 패턴을 쓰는 이유는 값이 아니라
    # 형태(늘어날 수 없는 구조)로 안전을 보장하기 위해서다.
    assigned_ids = candidates.filter(insights__isnull=False).values("pk")
    return candidates.filter(pk__in=assigned_ids), candidates.filter(insights__isnull=True)


def _run_cleanup(run_job_id: int) -> None:
    from apps.news.models import News
    from apps.setting.models import RunProposal
    from services.cleanup_prefilter import CRITERION_CODE, REASON, should_prefilter_delete
    from services.llm import PROMPT_VERSION, classify_news

    # 🔴 2026-09-16 "SET-010 검토 단위" 절 확정 — 이어하기 exclude 로직을 통째로
    # 걷어낸다. 대상을 "직전 배치 하나가 남긴 대기 제안"이 아니라 B(미판정, 위
    # cleanup_ab_split()) 그 자체로 정의하면 "이미 제안이 있는 기사는 정의상
    # 대상이 아니다"가 성립해 이어하기가 규칙이 아니라 정의가 된다. 배치를
    # 몇 번 나눠 돌리든, 중단되든, 실패하든 같은 기사가 두 번 판정될 길이
    # 구조적으로 없다 — previous_job을 찾아 "직전 하나"로 범위를 좁히던 종전
    # 방식이 안고 있던 "가장 최근 배치가 아니면 유령이 된다"는 문제 자체가
    # 사라진다(RunProposal.STATUS_PENDING만 보고, 그 제안을 어느 RunJob이
    # 냈는지·그 RunJob이 지금 무슨 상태인지는 안 본다).
    _, b_qs = cleanup_ab_split()
    targets = list(b_qs.order_by("pk"))
    RunJob.objects.filter(pk=run_job_id).update(
        target_count=len(targets), prompt_version=PROMPT_VERSION,
    )

    consecutive_failures = 0
    for news in targets:
        # 🔴 23차 개정(docs/planning.md 「SET-010 실행 중단」 9-3) — 「기사 하나가
        # 끝난 자리」는 여기다. 지금 시작하려는 이 기사를 처리하기 전에 확인하므로,
        # 이미 시작한 기사는 반드시 끝까지 처리하고 다음 기사로 넘어가려는 순간에만
        # 멈춘다.
        if _stop_requested(run_job_id):
            break

        # 🔴 2026-09-16 "2단계 비용 절감 정책" A안 — 제목과 본문 어디에도 AI 계열
        # 낱말이 없으면 LLM을 부르지 않고 코드가 바로 삭제 제안을 낸다. ExcludedURL
        # 직행이 아니라 RunProposal(TYPE_DELETE)로 내 검토 화면을 그대로 거친다
        # (형식 요건 2번, LLM을 안 부르니 토큰은 여전히 0). 본문이 짧으면(크롤 실패
        # 의심) should_prefilter_delete()가 스스로 False를 반환해 LLM 경로로 넘어간다
        # (형식 요건 5번 "의심되면 LLM으로").
        if should_prefilter_delete(news.title, news.body):
            RunProposal.objects.create(
                run_job_id=run_job_id, news=news, proposal_type=RunProposal.TYPE_DELETE,
                criterion_code=CRITERION_CODE, reason=REASON,
                judged_by=RunProposal.JUDGED_BY_CODE_AI_KEYWORD_RULE,
            )
            RunJob.objects.filter(pk=run_job_id).update(
                processed_count=F("processed_count") + 1, heartbeat_at=timezone.now(),
            )
            continue

        try:
            result = classify_news(news)
        except Exception as exc:
            consecutive_failures += 1
            RunJob.objects.filter(pk=run_job_id).update(
                failed_count=F("failed_count") + 1, heartbeat_at=timezone.now(),
            )
            # 🔴 23차 개정(docs/planning.md 「SET-010 검토 단위」 9번) — 이 News가
            # 판정 시도에서 제안 없이 끝난 누적 횟수. SET-010 화면이 이 값이 3
            # 이상인 자료를 "반복 실패"로 지목한다(apps/setting/views.py
            # _stuck_items()). SDK 내부 재시도는 여기 닿기 전에 이미 소진돼 한
            # 번으로 세어진다.
            News.objects.filter(pk=news.pk).update(
                classify_fail_count=F("classify_fail_count") + 1,
            )
            logger.warning(
                "News %s 판정 실패(연속 %d/%d): %s",
                news.pk, consecutive_failures, CLEANUP_STRUCTURAL_FAILURE_THRESHOLD, exc,
            )
            if consecutive_failures >= CLEANUP_STRUCTURAL_FAILURE_THRESHOLD:
                raise RuntimeError(
                    f"News {news.pk}까지 {consecutive_failures}건 연속 실패해 구조적 실패로 "
                    f"판단하고 배치를 끊어요. 마지막 오류: {exc}"
                ) from exc
            continue
        else:
            consecutive_failures = 0
            _save_proposals(run_job_id, news, result)
            # 🔴 2026-09-15 PE 신설 — classify_news()가 반환하는 _usage를 RunJob 배치
            # 합계에 누적한다(모델 docstring "건별이 아니라 배치 단위 합계로 둔 이유"
            # 참고). F() 표현식으로 원자 증가시킨다 — 폴링·다른 갱신과 겹쳐도 경합에
            # 안전한 이유는 processed_count와 같다.
            usage = result.get("_usage", {})
            RunJob.objects.filter(pk=run_job_id).update(
                processed_count=F("processed_count") + 1, heartbeat_at=timezone.now(),
                input_tokens=F("input_tokens") + usage.get("input_tokens", 0),
                output_tokens=F("output_tokens") + usage.get("output_tokens", 0),
                cache_creation_input_tokens=(
                    F("cache_creation_input_tokens") + usage.get("cache_creation_input_tokens", 0)
                ),
                cache_read_input_tokens=(
                    F("cache_read_input_tokens") + usage.get("cache_read_input_tokens", 0)
                ),
            )

    _run_dedup(run_job_id)


# 🔴 비교 창 — docs/planning.md "기준 2(동일 사건 중복 보도)를 2단계의 두 번째 LLM
# 호출로 옮긴다" 2-2-(b)(c) 확정. 길이는 상수(나중에 값만 바꿀 수 있다)이지만 기준점은
# "실행일"이 아니라 "이번 배치 신규분의 published_at 최솟값"이다(_run_dedup() 참고,
# 형태라 나중에 못 바꾼다 — 같은 문서 12번 표).
DEDUP_WINDOW_DAYS = 3

# 🔴 입력 상한 — 넘으면 조용히 좁히지 말고 로그로 보고한다(같은 문서 2-1-(d) ⚠️,
# 2-2-(b) ⚠️). 지금 규모(신규분 15~40건 + 3일 창 검증분 45~120건, 합 상한 약 160건)의
# 약 2배 여유를 둔다 — 며칠 밀린 배치는 앵커 때문에 창이 자동으로 늘어나므로(위 문서
# 2-2-(b) "사흘을 안 돌리다 오늘 돌리면 창이 6일이 된다"), 그 정상적인 확장을 상한
# 오판으로 잘못 알리지 않을 값이 필요하다.
DEDUP_MAX_INPUT_COUNT = 300


def _pick_dedup_representative(members):
    """묶음 안에서 대표를 결정론적으로 고른다(docs/design.md "SET-010 · 실행" 28차
    정정 ⑤번 대표 선정 순위). 🔴 이 함수는 "순수하게 우선순위만으로" 고를 때 쓴다 —
    창 밖 기존분 우선(0번), 이번 호출 안에서 이미 대표로 확정된 항목을 그대로 지키는
    스티키 규칙 같은 상위 규칙은 _run_dedup()이 이 함수를 부르기 전에 먼저 걸러낸다.
    그래서 이 함수는 "이미 기존분/스티키가 없는 순수 신규 묶음"과 "기존분끼리(또는
    스티키끼리) 여럿이 겹쳤을 때 그 부분집합 안에서 하나를 정하는" 두 자리 모두에서
    재사용된다 — 후자에 쓸 때는 그 부분집합만 members로 넘긴다.

    순위: 명시 연결(`has_explicit_link()`) 있는 것 > 본문이 가장 긴 것 > 발행이 가장
    이른 것 > pk가 가장 작은 것(마지막은 이 함수 안에서만 의미 있는 결정성 확보용
    tie-breaker다 — CLAUDE.md "정렬 일관성" 패턴).

    ⚠️ 매체 등급은 쓰지 않는다(같은 문서 5번 "이 프로젝트에 매체를 서열화한 데이터가
    없고, 없는 기준을 지어내지 않는다")."""
    from apps.news.services import has_explicit_link

    def sort_key(news):
        return (has_explicit_link(news), len(news.body), -news.published_at.timestamp(), -news.pk)

    return max(members, key=sort_key)


def _dedup_pick_reason(rep, from_existing):
    """duplicate_representative를 고른 이유 코드(RunProposal.DUP_PICK_REASON_*).

    🔴 세 값뿐이다(모델 choices) — "이번 호출 안에서 이미 대표로 확정됐다"(스티키)는
    네 번째 값을 새로 만들지 않는다. 스티키로 지켜진 대표도 애초에 처음 뽑힐 때는
    명시 연결 또는 본문 길이로 결정된 것이므로, 그 근거를 그대로 재확인해 반환한다 —
    "왜 대표인가"는 시점이 아니라 성질의 문제다."""
    from apps.news.services import has_explicit_link
    from apps.setting.models import RunProposal

    if from_existing:
        return RunProposal.DUP_PICK_REASON_EXISTING
    if has_explicit_link(rep):
        return RunProposal.DUP_PICK_REASON_LINKED
    return RunProposal.DUP_PICK_REASON_LONGEST


def _run_dedup(run_job_id: int) -> None:
    """SET-010 2단계 두 번째 LLM 호출 — 기준 2(동일 사건 중복 보도) 판정.
    docs/planning.md "기준 2(동일 사건 중복 보도)를 2단계의 두 번째 LLM 호출로
    옮긴다"(2026-09-17 확정), 그리고 그 다음 라운드 "코드가 후보를 좁히고 LLM은
    확인만 한다"(2-6)가 정본. `_run_cleanup()`의 건별 판정 루프가 끝난 뒤, 같은
    `RunJob` 안에서 이어 돈다.

    🔴 2026-09-17 2차 개정 — 배치 전체(신규 + 창 전량)를 한 번에 LLM에 묻던 방식을
    걷어낸다. 실측(같은 배치, 47건을 한 번에 물은 결과)이 묶음 0개·input 88,892
    토큰·약 124원을 냈다 — 성과 없이 비용만 썼다. 대신
    services/dedup_candidates.py의 find_duplicate_candidates()로 사건 지문·숫자
    토큰이 겹치는 후보 묶음을 코드가 먼저(0원) 좁히고, 후보 묶음마다 LLM에
    "확인"만 묻는다(2-6, PM "찾기가 아니라 확인입니다"). 🔴 후보가 0개면 LLM을
    아예 부르지 않는다 — 그 미호출을 판정 실패·"묶음 0개 판정"과 구분해 로그로
    남긴다(2-6-(d) "미호출을 실패·0건과 구분해 기록. 실측 124원이 성과 0에
    지불됐다").

    🔴 입력이 두 갈래다(같은 문서 2번 ①안 도식, 12번 "못 바꾼다" 표) — 이번 배치가
    "유지"로 제안한 신규분(삭제될 수 있는 쪽) + 비교 창 안의 검증 통과분(비교 대상
    전용, 이 호출로는 절대 삭제되지 않는다 — 2-1-(b)). ④에서 이미 "삭제"로 제안된
    건은 여기 넣지 않는다 — 버릴 기사를 두 번 묻지 않는다(같은 문서 2번 마지막 불릿).
    🔴 코드 후보 탐색(find_duplicate_candidates)은 신규분 + 창 전량을 합쳐서 한
    번에 돌린다 — 사건 지문·숫자 토큰은 신규/기존을 가리지 않고 겹칠 수 있어서다.
    다만 실제 LLM 호출은 후보 묶음 단위로 나뉘고, 신규분이 하나도 없는 후보(창 안
    기존분끼리만 묶인 것)는 이 호출로 손댈 것이 없어 LLM을 부르지 않는다.

    🔴 대표 선정은 LLM이 아니라 이 함수가 결정론적으로 한다. 묶음에 창 밖 기존분이
    하나라도 있으면 그 묶음은 신규분만 지우고 대표를 새로 정하지 않는다(0번,
    "기존분이 둘 이상이면 그 묶음에서는 신규만 지우고 대표를 새로 정하지 않는다").
    전부 신규분이면 `_pick_dedup_representative()`로 고른다.

    🔴 확정하면 삭제가 아니라 감춘다(2026-09-17 28차 정정) — `RunProposal.TYPE_DELETE`가
    아니라 `TYPE_DUPLICATE`를 만들고, 그 행에 `duplicate_representative`(묶음의 대표
    News)·`dup_fingerprint`(공통 표현)·`dup_pick_reason`(대표를 고른 이유)을 채운다.
    확정 뷰가 `duplicate_representative`를 그대로 대상 News의 `duplicate_of`에 넣는다
    (지우지 않는다) — `TYPE_DELETE`로 두면 확정 뷰가 "지울 것"과 "감출 것"을 DB에서
    되짚어 구분해야 하므로 타입 자체를 가른다.

    🔴 명시 연결(Insight/Report/OrgRelation)이 있는 News는 대표가 아니어도 삭제하지
    않는다 — `has_explicit_link()`로 방어한다. 정상 운영에서는 신규분이 아직 미검증이라
    이 방어가 걸릴 일이 없지만(명시 연결은 검증 통과 후에나 생긴다), 형태 자체는
    계약이므로 조건 없이 넣는다. 🔴 명시 연결이 묶음 안에 **둘 이상**이면(어느 쪽이
    핵심인지 코드가 판단할 근거가 없다) 대표를 정하지 않고 **hold**로 올린다 —
    `duplicate_representative`를 비워 둔 채 `TYPE_DUPLICATE`만 만들어, 확정 화면에서
    사람이 대표를 고르게 한다(지우지도 감추지도 않는다).

    🔴 **대표 flip 방어(같은 정정, PE 자체 발견)** — 이번 호출 "안에서" 이미 대표로
    확정된 News(신규분끼리 묶인 앞선 후보/묶음에서 승자가 된 것)는 뒤 묶음에서 다시
    평가하지 않고 그대로 대표를 지킨다(스티키). 실측 재현 조건: 같은 호출 안에서
    사건 지문이 셋 이상(A·B·C)을 잇는 다이아몬드 형태로 묶이면, LLM이 이를 두 개의
    별도 그룹({A,B}, {B,C})으로 나눠 응답할 수 있다 — 이때 스티키가 없으면 {A,B}에서
    B가 대표가 된 뒤 {B,C}를 처음부터 다시 평가해 C가 본문이 더 길다는 이유로 대표를
    빼앗을 수 있고, 그러면 A→B(구 대표)가 B→C(신 대표)를 가리키는 "대표의 대표"가
    생긴다(`News.verified()`가 기대는 "대표는 duplicate_of가 없다" 불변식이 깨짐).
    스티키가 둘 이상 부딪히면(서로 다른 앞선 묶음에서 각자 대표가 된 것끼리 나중에
    다시 묶임) 이미 커밋된 앞선 대표 지정을 되돌려 쓰는 복잡도를 피하려고 그 묶음은
    통째로 건너뛴다(로그만 남김) — 사람이 다음 배치에서 다시 보게 된다.

    🔴 **창 밖 기존분 사이의 결정성** — 한 묶음에 기존분이 둘 이상 섞이면(서로 다른
    배치에서 이미 확정된 대표 둘이 이번에 같은 사건으로 다시 묶인 경우) 예전엔
    `existing_member_ids[0]`(LLM 응답 순서에 좌우되는 임의 순서)을 그대로 썼다 —
    CLAUDE.md "정렬 일관성" 패턴 위반이라 실행마다 다른 기존분에 신규분이 붙을 수
    있었다. 이제 `_pick_dedup_representative()`로 그 기존분 부분집합 안에서마저
    결정론적으로 고른다(신규분을 어느 기존 대표에 붙일지만 정하며, 기존 대표 둘을
    서로 병합하지는 않는다 — 기존 News에는 이번 호출로 건드릴 RunProposal 자체가
    없어서 구조적으로 못 한다. 로그로 남겨 사람이 보게 한다).

    예외는 여기서 잡지 않는다 — `_run_insight()`와 같은 이유로 `_execute()`의 바깥
    try/except가 받아 RunJob을 실패로 남긴다. 후보 묶음마다 트랜잭션을 따로 묶으므로,
    뒤 묶음 호출이 실패해도 이미 처리한 앞선 묶음의 판정(RunProposal)은 유효하게
    남는다(`cleanup_ab_split()` 독스트링과 같은 원칙)."""
    from apps.news.models import News
    from apps.news.services import has_explicit_link
    from apps.setting.models import RunProposal
    from services.dedup_candidates import find_duplicate_candidates
    from services.llm import PROMPT_VERSION_DEDUP, find_duplicate_news

    keep_proposals = list(
        RunProposal.objects.filter(
            run_job_id=run_job_id, proposal_type=RunProposal.TYPE_KEEP,
            status=RunProposal.STATUS_PENDING,
        ).select_related("news")
    )
    if not keep_proposals:
        return

    new_batch = [p.news for p in keep_proposals]
    proposal_by_news_id = {p.news_id: p for p in keep_proposals}
    new_batch_ids = set(proposal_by_news_id)

    # 🔴 앵커 — "실행일"이 아니라 "이번 배치 신규분의 published_at 최솟값"(2-2-(b)).
    # 검증 지연이 배치를 갈라놓는 경로(놓치는 경로 6번)를 구조적으로 닫는 자리다.
    anchor = min(news.published_at for news in new_batch)
    window_start = anchor - timedelta(days=DEDUP_WINDOW_DAYS)
    window_news = list(
        News.objects.verified()
        .filter(published_at__gte=window_start, published_at__lte=timezone.now())
        .exclude(pk__in=new_batch_ids)
        .order_by("published_at")
    )

    total_input = len(new_batch) + len(window_news)
    if total_input > DEDUP_MAX_INPUT_COUNT:
        logger.warning(
            "RunJob %s 중복 판정 입력이 상한(%d)을 넘었어요(신규 %d + 창 %d일 %d건 = %d). "
            "몰래 좁히지 않고 그대로 후보 탐색을 돌려요.", run_job_id, DEDUP_MAX_INPUT_COUNT,
            len(new_batch), DEDUP_WINDOW_DAYS, len(window_news), total_input,
        )

    current_version = RunJob.objects.filter(pk=run_job_id).values_list(
        "prompt_version", flat=True,
    ).first() or ""
    combined_version = f"{current_version}+{PROMPT_VERSION_DEDUP}" if current_version else PROMPT_VERSION_DEDUP
    RunJob.objects.filter(pk=run_job_id).update(prompt_version=combined_version)

    all_news = new_batch + window_news
    news_by_id = {news.pk: news for news in all_news}
    known_ids = set(news_by_id)

    # 🔴 대표 flip에 대한 마지막 방어선(2026-09-17, 그래프 담당 PE 지적 — GRAPH-001
    # 엣지 임계가 "대표는 duplicate_of가 없다" 불변식에 의존한다, apps/graph/views.py
    # 49-52·78-88 "묶음마다 대표 1건은 반드시 남아 공동언급이 0으로 떨어지지 않는다").
    # 위 0번(창 밖 기존분 우선)·스티키(이번 호출 안 대표 유지) 분기가 이미 이 불변식을
    # 구조적으로 지킨다 — 새로 만드는 신규분 pk는 애초에 기존 대표일 수 없고, 창 안
    # 기존분은 이 함수가 그 News의 RunProposal 자체를 건드리지 않는다(존재하지 않는다).
    # 그래도 분기 로직이 나중에 바뀌어도 조용히 깨지지 않도록, 실제로 변환(TYPE_DUPLICATE/
    # hold)하는 시점에 한 번 더 확인한다 — 이미 다른 News가 duplicate_of로 가리키는
    # News(다른 배치에서 이미 확정된 대표)는 어떤 경우에도 감추거나 hold로 바꾸지 않는다.
    established_rep_ids = set(
        News.objects.filter(duplicate_of__isnull=False)
        .values_list("duplicate_of_id", flat=True).distinct()
    )

    candidate_groups = find_duplicate_candidates(all_news)
    if not candidate_groups:
        # 🔴 미호출 — 판정 실패도 "묶음 0개 판정"도 아니다. LLM을 아예 부르지
        # 않았다는 사실 자체를 구분해 로그로 남긴다(2-6-(d)).
        logger.info(
            "RunJob %s 중복 판정 — 코드 후보 0묶음이라 LLM을 호출하지 않았어요"
            "(신규 %d건 + 창 %d일 검증분 %d건 검사).",
            run_job_id, len(new_batch), DEDUP_WINDOW_DAYS, len(window_news),
        )
        return

    converted = 0
    held = 0
    protected = 0
    conflict_skipped = 0
    call_count = 0
    llm_group_total = 0
    # 🔴 이번 호출 안에서 "이미 처리를 마쳤다"(감춰졌거나 hold로 올라갔다)고 확정된
    # 신규분 pk. 뒤 묶음의 member_ids 필터링에 계속 반영해 두 번 처리하지 않는다.
    resolved_pks = set()
    # 🔴 이번 호출 안에서 "이미 대표로 확정됐다"(스티키)고 결정된 신규분 pk. 뒤 묶음이
    # 이 pk를 다시 만나면 처음부터 다시 뽑지 않고 그대로 대표를 지킨다(대표 flip 방어,
    # 독스트링 참고).
    sticky_rep_pks = set()

    for candidate in candidate_groups:
        group_new = [news_by_id[pk] for pk in candidate.news_ids if pk in new_batch_ids]
        group_existing = [news_by_id[pk] for pk in candidate.news_ids if pk not in new_batch_ids]
        if not group_new:
            # 창 안 기존분끼리만 묶인 후보 — 이 호출로는 손댈 것이 없다(5-1).
            # LLM을 부르지 않는다.
            continue

        call_count += 1
        result = find_duplicate_news(
            group_new, group_existing,
            matched_signals=sorted(candidate.matched_signals),
            over_soft_cap=candidate.over_soft_cap,
        )
        groups = result.get("groups", [])
        llm_group_total += len(groups)

        with transaction.atomic():
            for group in groups:
                # 응답은 신뢰하되 검증한다(_run_insight()의 news_ids 매칭과 같은
                # 원칙) — 이번 호출 밖의 pk나 이미 처리한 pk는 건너뛴다.
                member_ids = [
                    pk for pk in group.get("news_ids", [])
                    if pk in known_ids and pk not in resolved_pks
                ]
                if len(member_ids) < 2:
                    continue

                new_member_ids = [pk for pk in member_ids if pk in new_batch_ids]
                existing_member_ids = [pk for pk in member_ids if pk not in new_batch_ids]
                if not new_member_ids:
                    # 창 안 기존분끼리만 묶였다 — 이 호출로는 손대지 않는다(5-1
                    # "기존분이 둘 이상이면 그 묶음에서는 신규만 지우고 대표를 새로
                    # 정하지 않는다").
                    continue

                sticky_new_ids = [pk for pk in new_member_ids if pk in sticky_rep_pks]

                if existing_member_ids and sticky_new_ids:
                    # 🔴 충돌 — 창 밖 기존 대표와 이번 호출 안에서 이미 확정된 신규
                    # 대표가 한 묶음에서 만났다. 기존 News에는 이번 호출로 건드릴
                    # RunProposal이 없어 "둘 중 하나로 병합"을 안전하게 실행할 방법이
                    # 없다(앞서 커밋된 신규 대표 지정을 되돌려 쓰는 것도 위험하다).
                    # 지우지도 감추지도 않고 그대로 건너뛴다 — 사람이 다음 배치에서
                    # 다시 보게 된다.
                    conflict_skipped += 1
                    logger.warning(
                        "News %s는 창 밖 기존 대표와 이번 호출 안 신규 대표(스티키 %s)가 "
                        "한 묶음에서 만나 자동으로 병합할 수 없어요. 건너뛰어요.",
                        sorted(member_ids), sorted(sticky_new_ids),
                    )
                    continue

                if len(sticky_new_ids) > 1:
                    # 🔴 충돌 — 서로 다른 앞선 묶음에서 각자 대표가 된 신규분 둘이 이번
                    # 묶음에서 다시 만났다. 어느 한쪽을 대표로 정하면 이미 커밋된 다른
                    # 쪽의 앞선 판정(그 대표를 가리키는 RunProposal들)을 다시 써야 하는데,
                    # 그 재작성은 하지 않는다(대표 flip 방어와 같은 이유). 건너뛴다.
                    conflict_skipped += 1
                    logger.warning(
                        "News %s는 이번 호출 안에서 이미 대표가 된 신규분이 둘 이상(%s) "
                        "섞여 있어 자동으로 병합할 수 없어요. 건너뛰어요.",
                        sorted(member_ids), sorted(sticky_new_ids),
                    )
                    continue

                fingerprint = group.get("fingerprint", "")
                dup_fingerprint = [fingerprint] if fingerprint else []

                if existing_member_ids:
                    # 0번 — 창 밖 기존분이 하나라도 있으면 무조건 대표다. 신규만
                    # 지운다(감춘다). 기존분이 둘 이상이면 그 부분집합 안에서마저
                    # 결정론적으로 골라 붙인다(독스트링 "창 밖 기존분 사이의 결정성").
                    if len(existing_member_ids) == 1:
                        rep_pk = existing_member_ids[0]
                    else:
                        rep_pk = _pick_dedup_representative(
                            [news_by_id[pk] for pk in existing_member_ids]
                        ).pk
                        logger.warning(
                            "News %s는 서로 다른 기존 대표(%s)가 한 묶음으로 묶였어요 — "
                            "신규분은 %s에 붙이지만, 기존 대표 두 묶음 자체의 병합은 "
                            "이 호출로 하지 않아요(사람 확인 필요).",
                            sorted(member_ids), sorted(existing_member_ids), rep_pk,
                        )
                    to_hold_ids = []
                    to_delete_ids = new_member_ids
                    pick_reason = _dedup_pick_reason(news_by_id[rep_pk], from_existing=True)
                elif sum(1 for pk in member_ids if has_explicit_link(news_by_id[pk])) >= 2:
                    # 🔴 명시 연결이 둘 이상 — 어느 쪽이 핵심인지 코드가 판단할
                    # 근거가 없다. 대표를 정하지 않고 hold로 올린다(지우지도 감추지도
                    # 않는다). existing_member_ids가 비어 있으므로 대상은 전부 신규분.
                    rep_pk = None
                    pick_reason = ""
                    to_delete_ids = []
                    to_hold_ids = new_member_ids
                else:
                    rep = sticky_new_ids[0] if sticky_new_ids else None
                    if rep is None:
                        rep = _pick_dedup_representative([news_by_id[pk] for pk in member_ids]).pk
                    rep_pk = rep
                    to_hold_ids = []
                    to_delete_ids = [pk for pk in new_member_ids if pk != rep_pk]
                    pick_reason = _dedup_pick_reason(news_by_id[rep_pk], from_existing=False)

                if rep_pk is not None:
                    sticky_rep_pks.add(rep_pk)

                for pk in to_hold_ids:
                    if pk in established_rep_ids or pk in sticky_rep_pks:
                        # 대표 flip 방어선(마지막 확인) — 이론상 도달하지 않는다(위
                        # 설명 참고). 도달하면 분기 로직에 버그가 있다는 뜻이라 조용히
                        # 넘기지 않고 error로 남긴다.
                        conflict_skipped += 1
                        logger.error(
                            "News %s는 이미 다른 기사의 대표인데 hold로 전환하려 했어요 — "
                            "대표 flip 방어선이 막았어요. 분기 로직 버그 의심, 건너뛰어요.", pk,
                        )
                        continue
                    proposal = proposal_by_news_id[pk]
                    proposal.proposal_type = RunProposal.TYPE_DUPLICATE
                    proposal.criterion_code = "2"
                    proposal.duplicate_representative = None
                    proposal.dup_fingerprint = dup_fingerprint
                    proposal.dup_pick_reason = ""
                    proposal.reason = (
                        f"동일 사건 중복 보도로 보이나 명시 연결(근거)이 둘 이상 걸려 "
                        f"코드가 대표를 정하지 못했어요. 사건 지문: {fingerprint}. "
                        f"사람 확인이 필요해요."
                    )
                    proposal.save(update_fields=[
                        "proposal_type", "criterion_code", "duplicate_representative",
                        "dup_fingerprint", "dup_pick_reason", "reason",
                    ])
                    resolved_pks.add(pk)
                    held += 1

                for pk in to_delete_ids:
                    if pk in established_rep_ids or pk in sticky_rep_pks:
                        # 대표 flip 방어선(마지막 확인) — 이론상 도달하지 않는다(위
                        # established_rep_ids 정의 참고). 도달하면 분기 로직에 버그가
                        # 있다는 뜻이라 조용히 넘기지 않고 error로 남긴다.
                        conflict_skipped += 1
                        logger.error(
                            "News %s는 이미 다른 기사의 대표인데 감춤으로 전환하려 했어요 — "
                            "대표 flip 방어선이 막았어요. 분기 로직 버그 의심, 건너뛰어요.", pk,
                        )
                        continue
                    if has_explicit_link(news_by_id[pk]):
                        # 대표가 아니어도 명시 연결이 있으면 남긴다(위 hold 분기가
                        # "묶음 안에 2건 이상"을 이미 걸렀으므로, 여기 걸리는 것은
                        # "묶음 안에 정확히 1건"인데 그 1건이 대표로 뽑히지 않은
                        # 경우다 — 대표 선정 우선순위가 명시 연결을 최우선으로 두므로
                        # 정상 운영에서는 일어나지 않지만, 방어로 남긴다).
                        protected += 1
                        logger.warning(
                            "News %s는 중복 묶음(대표 News %s)에 속하지만 명시 연결이 있어 "
                            "감춤 제안으로 바꾸지 않아요.", pk, rep_pk,
                        )
                        continue
                    proposal = proposal_by_news_id[pk]
                    proposal.proposal_type = RunProposal.TYPE_DUPLICATE
                    proposal.criterion_code = "2"
                    proposal.duplicate_representative_id = rep_pk
                    proposal.dup_fingerprint = dup_fingerprint
                    proposal.dup_pick_reason = pick_reason
                    proposal.reason = f"동일 사건 중복 보도. 사건 지문: {fingerprint}. 대표 News {rep_pk}."
                    proposal.save(update_fields=[
                        "proposal_type", "criterion_code", "duplicate_representative",
                        "dup_fingerprint", "dup_pick_reason", "reason",
                    ])
                    resolved_pks.add(pk)
                    converted += 1

        usage = result.get("_usage", {})
        RunJob.objects.filter(pk=run_job_id).update(
            heartbeat_at=timezone.now(),
            input_tokens=F("input_tokens") + usage.get("input_tokens", 0),
            output_tokens=F("output_tokens") + usage.get("output_tokens", 0),
            cache_creation_input_tokens=(
                F("cache_creation_input_tokens") + usage.get("cache_creation_input_tokens", 0)
            ),
            cache_read_input_tokens=(
                F("cache_read_input_tokens") + usage.get("cache_read_input_tokens", 0)
            ),
        )

    logger.info(
        "RunJob %s 중복 판정 완료 — 코드 후보 %d묶음, LLM 호출 %d회(신규 없는 후보 %d개는 "
        "건너뜀), LLM이 확인한 실제 중복 묶음 %d개, 감춤 전환 %d건, hold %d건, "
        "명시 연결로 보호 %d건, 자동 병합 불가로 건너뜀 %d건.",
        run_job_id, len(candidate_groups), call_count, len(candidate_groups) - call_count,
        llm_group_total, converted, held, protected, conflict_skipped,
    )


def _run_insight(run_job_id: int) -> None:
    """SET-010 조사 축 3단계(주요 이슈) — docs/planning.md "3~5단계를 LLM으로 옮기는
    설계"가 정본. 2단계와 정반대로 배치 전체를 한 번에 호출한다(같은 문서 7-(a)).

    🔴 건별 루프가 아니라 호출 1회다 — 그래서 CLEANUP_STRUCTURAL_FAILURE_THRESHOLD 같은
    연속 실패 카운터가 없다. generate_insights()가 던지는 예외를 여기서 잡지 않고
    그대로 올려보낸다 — _execute()의 바깥 try/except가 그 예외를 받아 RunJob을 실패로
    남긴다(설계 9-(a) "실패하면 이 배치는 처음부터 다시 돈다", 9-(c) "1회면 그대로
    실패로 남긴다"). 부분 저장도 하지 않는다(9-(d)) — RunDraft 생성을 트랜잭션 하나로
    묶어, 응답 파싱 뒤 저장 중 한 건이라도 실패하면 전부 롤백된다.

    🔴 대상은 "검증된 News 중 어느 Insight에도 아직 안 묶인 것"이다(설계 2번 잠금 표
    "검증된 News 중 어느 Insight에도 안 묶인 것이 0건이면 잠근다"의 반대편 — 그 표가
    말하는 "이슈로 묶을 뉴스"가 바로 이 쿼리의 대상이다). 이미 어느 Insight에든 묶인
    News는 다시 대상에 넣지 않는다 — "기존 Insight에 새 기사를 붙이는 갱신 경로는
    이번 범위 밖"(설계 10번 "미루는 것").

    🔴 processed_count는 "생성된 이슈 수"가 아니라 target_count와 같은 값(len(targets))을
    쓴다. LLM이 한 번에 전체 입력을 고려해 판정했다는 뜻에서 "처리를 마친 기사 수"라는
    기존 필드 의미(cleanup과 동일)를 유지한다 — 이슈로 묶이지 않고 남은 기사도 "고려는
    됐다"는 점에서 처리를 마친 것이다. 새 필드를 만들지 않는다(진행 표시 국면 세분화는
    다음 라운드, docs/planning.md "SET-010 진행 표시" 절)."""
    from apps.news.models import News
    from apps.setting.models import RunDraft
    from services.llm import PROMPT_VERSION_INSIGHT, generate_insights

    # 🔴 2026-09-16 "SET-010 검토 단위" 절 11번 — insight_dismissed_at이 찍힌
    # News(3단계 탈락 표식)를 대상에서 뺀다. 3단계 대상이 "직전 확정 이후 새로
    # 검증된 것"(증분형)에서 "탈락 표식 없는 미배정 전체"로 바뀌었으므로, 표식이
    # 없으면 한 번 탈락한 기사가 실행마다 계속 다시 대상이 되어 3단계가 영구히
    # "할 일 있음"이 된다(같은 이유로 탈락한다는 것이 구조이기 때문).
    #
    # 🔴 2026-09-16 조인 중복 감사(insight_ab_split()의 실측 사고 정정과 같은
    # 라운드) — 이 쿼리는 안전하다. insights__isnull=True는 M2M을 LEFT JOIN하되
    # "묶인 이슈가 하나도 없다"를 묻는 것이라 늘어날 행 자체가 없다(이슈가 여러
    # 개 묶인 경우에만 JOIN이 행을 늘리는데, 그 경우는 정의상 isnull=False다).
    # insight_ab_split()의 unassigned도 같은 이유로 원래 안전했다(실측: 17=17).
    targets = list(
        News.objects.verified()
        .filter(insights__isnull=True, insight_dismissed_at__isnull=True)
        .order_by("published_at", "pk")
    )
    run_job = RunJob.objects.get(pk=run_job_id)
    run_job.target_count = len(targets)
    run_job.prompt_version = PROMPT_VERSION_INSIGHT
    run_job.save(update_fields=["target_count", "prompt_version"])
    # 🔴 이 배치가 "고려한 후보 전체"를 얼려 둔다 — RunDraft.news는 실제로 이슈로
    # 묶인 것만 담아 "고려했지만 어디에도 안 묶인 것"을 알 방법이 없다. 확정
    # 시점(apps/setting/views.py _confirm_insight_drafts())에 이 집합에서 채택된
    # Insight의 news를 뺀 나머지가 탈락 표식을 받는다.
    run_job.insight_candidates.set(targets)
    if not targets:
        # 대상 0건 — 화면 잠금(설계 2번)이 이 상태를 막는 정상 경로이지만, 관리 명령
        # 등으로 직접 불렸을 때를 대비해 방어적으로 그대로 완료 처리한다. RunDraft를
        # 하나도 만들지 않으면 검토 화면은 "채택할 것이 없다"로 정상 렌더된다.
        return

    result = generate_insights(targets)

    news_by_id = {news.pk: news for news in targets}
    issues = result.get("issues", [])
    drafts = []
    with transaction.atomic():
        for issue in issues:
            draft = RunDraft.objects.create(
                run_job_id=run_job_id,
                draft_type=RunDraft.TYPE_INSIGHT,
                title=issue["title"],
                content=issue["content"],
                implication=issue["implication"],
                grade=issue["grade"],
                grade_reason=issue.get("grade_reason", ""),
                # 🔴 2026-09-17 신설 — 축약본 문장 번호(RA 손 작업을 전부 단계 안으로
                # 넣는다 3번). content_short/implication_short 자체는 여기서 만들지
                # 않는다 — 확정 시점에 build_short_field()로 만든다(_confirm_insight_drafts()).
                # 검토 화면은 이 인덱스로 content_sentences를 다시 만들어 취소선을 그린다.
                content_keep=issue.get("content_keep", []),
                implication_keep=issue.get("implication_keep", []),
            )
            # 응답의 news_ids 중 이번 배치 대상에 실제로 있는 것만 연결한다 — LLM이
            # 존재하지 않는 id를 냈을 가능성을 방어한다(응답은 신뢰하되 검증한다).
            matched = [news_by_id[nid] for nid in issue.get("news_ids", []) if nid in news_by_id]
            draft.news.set(matched)
            drafts.append(draft)

    usage = result.get("_usage", {})
    RunJob.objects.filter(pk=run_job_id).update(
        processed_count=len(targets), heartbeat_at=timezone.now(),
        input_tokens=F("input_tokens") + usage.get("input_tokens", 0),
        output_tokens=F("output_tokens") + usage.get("output_tokens", 0),
        cache_creation_input_tokens=(
            F("cache_creation_input_tokens") + usage.get("cache_creation_input_tokens", 0)
        ),
        cache_read_input_tokens=(
            F("cache_read_input_tokens") + usage.get("cache_read_input_tokens", 0)
        ),
    )

    # 🔴 2026-09-17 신설 — 3단계 두 번째 호출(관계 추출, docs/planning.md "지식그래프
    # 관계 라벨링을 3단계의 두 번째 LLM 호출로 옮긴다"). 이슈 초안 저장(위 트랜잭션)이
    # 끝난 뒤에 둔다 — 이 호출은 이슈 초안과 데이터를 주고받지 않지만, 이슈 저장이
    # 실패하면(예외가 올라가 _execute()가 RunJob을 실패로 남긴다) 여기까지 오지
    # 않아야 순서가 맞다. 실패가 격리된다(services/llm.py extract_relations()
    # docstring) — 관계 호출 실패는 여기서 잡아 로그만 남기고 이슈 초안·헤드라인
    # 순위는 그대로 진행한다.
    _run_relation_extraction(run_job_id, targets)

    # 🔴 2026-09-17 신설 — 3단계 세 번째 호출(헤드라인 순위, docs/planning.md "RA 손
    # 작업을 전부 단계 안으로 넣는다" 2번). 이번 배치 이슈 초안이 만들어진 뒤라야
    # 후보(1급 초안)의 pk가 있다 — 그래서 순서상 여기다.
    _run_insight_headliner(run_job_id, drafts)


def _run_relation_extraction(run_job_id: int, targets) -> None:
    """3단계 두 번째 호출 — 지식그래프 관계 추출(docs/planning.md "지식그래프 관계
    라벨링을 3단계의 두 번째 LLM 호출로 옮긴다"가 정본). targets는 _run_insight()가
    이슈 판정에 넣은 것과 같은 배치다(3-1 근거 3 "재료가 같다").

    🔴 배치 전체를 한 번에 묻는다(건별·이슈별로 쪼개지 않는다) — PE 판단, 근거는
    셋이다. ① planning.md 3번이 이미 이 자리를 "배치 전체 1회 호출"로 확정했고,
    쪼개는 안은 그 결정을 뒤집는 것이라 반박 근거가 따로 있어야 한다(문서가 요구하는
    수준). ② 관계는 "여러 기사에 걸친 근거"를 봐야 하는 경우가 있어(3번 "기사 A: 코리안리가
    로민과 협업 / 기사 B: 로민이 다른 보험사와도 계약" 예시) 이슈별로 쪼개면 그 이슈에
    없는 기사의 근거를 원리적으로 못 본다 — 건별 호출이 여러 기사에 걸친 관계를
    "원리적으로 못 본다"는 문제를 되살린다. ③ 2단계 중복 판정이 47건 배치에서 놓친
    사고(묶음 0개)는 "많은 후보 쌍을 서로 비교"해야 하는 조합적 과제였다 — 관계
    추출은 그와 달리 기사 하나하나를 순서대로 읽으며 서술어를 찾는 과제이고, 3단계
    이슈 판정(같은 크기의 배치)이 이미 안정적으로 배치 전체 1회로 돌고 있다(이번
    라운드 이전부터 프로덕션 경로). 다만 이 판단은 실측 전이다 — 되돌림 조건은
    14번 표의 "관계 초안이 3배치 연속 0건"과 이 함수가 남기는 malformed_rejected/
    type_rejected 로그가 진다.

    🔴 실패가 격리된다 — 이 함수 전체를 감싼다(아래 넓은 except가 그 경계다. 원인은
    ①extract_relations()가 이미 좁게 잡은 뒤 LLMStructuralError/LLMJudgmentError로
    좁혀 던지므로 여기서 다시 좁힐 실익이 없고, ②이슈 초안(위 트랜잭션)은 이미
    커밋됐으므로 이 함수의 어떤 실패든 — LLM 호출이든 그 아래 코드 검증 버그든 —
    3단계 전체를 실패(STATUS_FAILED)로 만들면 안 된다는 것이 설계 요구사항이기
    때문이다(3-1 근거 4 "실패가 격리된다"). RunJob이 실패로 남으면 이미 만든 이슈
    초안이 검토 화면에서 사라진다 — 그걸 막는 것이 이 경계의 존재 이유다. 삼키지
    않는다 — logger.exception()이 traceback을 남긴다.

    🔴 코드가 두 번 거른다(4번 "코드에서도 한 번 더 거른다. 프롬프트만 믿지 않는다").
    ① 타입 제약(ALLOWED_TYPE_PAIRS) 밖의 쌍, ② 이미 OrgRelation이 있는 쌍(6번 —
    확정 시점이 아니라 여기, 제안 생성 시점에 거른다) 은 제안 자체를 만들지 않는다.
    ①은 "코드가 버린 건수"로 로그에 남기고(4번 말미), ②는 RunJob.relation_skipped_count/
    relation_conflict_count로 남긴다(13번 PE 인계 5번) — 화면(run_review.html)이 이미
    이 두 값을 읽게 그려져 있다."""
    from apps.graph.views import ALLOWED_TYPE_PAIRS
    from apps.setting.models import OrgRelation, RunDraft, normalize_org_pair
    from services.llm import PROMPT_VERSION_RELATION, RELATION_LABELS, build_relation_org_index, extract_relations

    try:
        org_index = build_relation_org_index(targets)
        result = extract_relations(targets, org_index)

        news_by_id = {news.pk: news for news in targets}
        org_count = len(org_index)

        skipped_count = 0
        conflict_count = 0
        type_rejected = 0
        malformed_rejected = 0

        with transaction.atomic():
            for item in result.get("relations", []):
                a_idx, b_idx = item.get("org_a_index"), item.get("org_b_index")
                label = item.get("label", "")
                matched_news = [news_by_id[nid] for nid in item.get("news_ids", []) if nid in news_by_id]
                valid_indices = (
                    isinstance(a_idx, int) and isinstance(b_idx, int)
                    and a_idx != b_idx and 1 <= a_idx <= org_count and 1 <= b_idx <= org_count
                )
                if not valid_indices or label not in RELATION_LABELS or not matched_news:
                    # 응답은 신뢰하되 검증한다(_run_insight()의 news_ids 방어와 같은 원칙) —
                    # 스키마가 이미 enum·정수를 강제하지만 인덱스 범위·자기 자신 쌍·근거
                    # 기사 매칭은 스키마가 못 잡는다.
                    malformed_rejected += 1
                    continue

                org_a, org_b = org_index[a_idx - 1], org_index[b_idx - 1]
                if frozenset({org_a.org_type, org_b.org_type}) not in ALLOWED_TYPE_PAIRS:
                    type_rejected += 1
                    continue

                lo_pk, hi_pk = normalize_org_pair(org_a.pk, org_b.pk)
                existing = OrgRelation.objects.filter(org_a_id=lo_pk, org_b_id=hi_pk).first()
                if existing is not None:
                    skipped_count += 1
                    if existing.label != label:
                        conflict_count += 1
                    continue

                draft = RunDraft.objects.create(
                    run_job_id=run_job_id,
                    draft_type=RunDraft.TYPE_RELATION,
                    title=f"{org_a.name} × {org_b.name} — {label}",
                    content=item.get("reason", ""),
                    relation_org_a=org_a,
                    relation_org_b=org_b,
                    relation_label=label,
                )
                draft.news.set(matched_news)

        if type_rejected or malformed_rejected:
            logger.warning(
                "RunJob %s 관계 추출 — 코드가 버린 제안 %d건(타입 제약 위반 %d건, 형식 불량 %d건).",
                run_job_id, type_rejected + malformed_rejected, type_rejected, malformed_rejected,
            )

        current_version = RunJob.objects.filter(pk=run_job_id).values_list(
            "prompt_version", flat=True,
        ).first() or ""
        combined_version = (
            f"{current_version}+{PROMPT_VERSION_RELATION}" if current_version else PROMPT_VERSION_RELATION
        )
        usage = result.get("_usage", {})
        RunJob.objects.filter(pk=run_job_id).update(
            prompt_version=combined_version,
            relation_skipped_count=skipped_count,
            relation_conflict_count=conflict_count,
            heartbeat_at=timezone.now(),
            input_tokens=F("input_tokens") + usage.get("input_tokens", 0),
            output_tokens=F("output_tokens") + usage.get("output_tokens", 0),
            cache_creation_input_tokens=(
                F("cache_creation_input_tokens") + usage.get("cache_creation_input_tokens", 0)
            ),
            cache_read_input_tokens=(
                F("cache_read_input_tokens") + usage.get("cache_read_input_tokens", 0)
            ),
        )
    except Exception:
        logger.exception(
            "RunJob %s 관계 추출이 실패했어요 — 이슈 초안은 영향을 받지 않아요.", run_job_id,
        )


# 5-1 "업권을 가르는 기준" — 다양성 집계에서 항상 빼는 두 특수 sector 값.
_HEADLINER_SECTOR_PASSTHROUGH = frozenset({
    "여러 업권",  # services.llm.HEADLINER_SECTOR_MULTI와 같은 문자열(모듈 경계를 넘는
    "업권 없음",  # 리터럴 비교라 드리프트 위험이 있지만, 순환 임포트를 피하려고 상수
})                # 공유 대신 문자열을 그대로 복제했다 — 값은 5-1 원문 그대로 고정이다.

HEADLINER_CAP = 3  # 2-4 상한 3 강제 자리 다섯 중 하나(② 확정 뷰가 아니라 여기 — 코드가
# 만드는 picks 자체가 이 상한을 넘지 않는다. LLM 스키마 maxItems=3과 함께 이중으로 막는다).
HEADLINER_SECTOR_CAP = 2  # 5-1 "3자리에 같은 업권은 2건까지".


def _run_insight_headliner(run_job_id: int, issue_drafts) -> None:
    """3단계 세 번째 LLM 호출 — 헤드라인 순위(docs/planning.md "RA 손 작업을 전부
    단계 안으로 넣는다" 2번이 정본). issue_drafts는 이번 배치가 방금 만든 이슈
    초안(RunDraft.TYPE_INSIGHT) 목록이다.

    🔴 1-B 창 결정 규칙 6단계를 코드/LLM으로 그대로 쪼갠다(2-1) — 1~3단계(1급 집합,
    기준점, 창)는 여기 코드가, 4~6단계((ii)→(i)→서사 사슬, 중복 제외, 다양성 라벨)는
    services.llm.rank_headliners()가 맡는다. 다양성 최종 집계(같은 업권 2건 상한)는
    LLM 출력을 받은 뒤 이 함수가 코드로 강제한다(2-1 "LLM이 업권 라벨을 내고 코드가
    센다").

    🔴 후보가 0건이면(창 안 1급이 하나도 없음) 조용히 끝낸다 — 4번 "지정 0건이면
    영역을 통째로 그리지 않는다"의 입력 쪽이다. LLM 호출 자체를 만들지 않는다(비용)."""
    from apps.news.models import Insight, News
    from apps.setting.models import RunDraft
    from services.llm import rank_headliners

    batch_grade1 = [d for d in issue_drafts if d.grade == Insight.GRADE_1]
    existing_grade1 = list(Insight.objects.filter(grade=Insight.GRADE_1))

    # 기준점 — 그 시점 검증된 News 중 최신 발행일. "오늘"을 쓰지 않는다(1-B).
    reference = News.objects.verified().aggregate(m=Max("published_at"))["m"]
    if reference is None:
        return  # 검증된 News가 아예 없다 — 후보 계산 자체가 성립하지 않는다.

    def _latest_news_at(candidate):
        dates = list(candidate.news.values_list("published_at", flat=True))
        return max(dates) if dates else None

    def _pool_at(days):
        # 🔴 경계일은 창 안이다 — 부등호는 `<=`로 읽는다(1-B ⚠️ "하루 차이로
        # 헤드라이너가 갈리는 자리에 판정자 재량을 남기지 않는다"). 근거뉴스가 하나도
        # 없는 후보(이론상 나올 수 없지만 방어)는 창 판정 자체가 성립하지 않으므로
        # 항상 제외한다.
        result = []
        for c in (batch_grade1 + existing_grade1):
            latest = _latest_news_at(c)
            if latest is not None and (reference - latest).days <= days:
                result.append(c)
        return result

    # 2~3단계 — 7일 창, 미달(3건 미만)이면 14일로 한 단계만 확장(1-B "창 결정 규칙").
    window = 7
    pool = _pool_at(window)
    if len(pool) < 3:
        window = 14
        pool = _pool_at(window)

    # 직전 지정(전량 교체 전 스냅샷) — 5-2 판정 승계·기록 의무의 재료. 이 함수가
    # 끝나기 전까지는 Insight.headliner_order가 아직 그대로다(확정 전이므로).
    prev_qs = list(Insight.objects.filter(headliner_order__isnull=False).order_by("headliner_order"))
    prev_by_pk = {i.pk: i.headliner_order for i in prev_qs}

    window_label = (
        f"창 {window}일 · 기준점 {timezone.localtime(reference):%m.%d} · 후보 1급 {len(pool)}건"
    )
    if not pool:
        RunJob.objects.filter(pk=run_job_id).update(headliner_window_label=window_label)
        return

    # 후보 풀에 임시 id를 매긴다(LLM이 그 번호로 picks를 되돌려준다) — News.pk와
    # RunDraft.pk가 같은 값 공간을 쓸 수 있어(둘 다 DB pk) 후보 자체의 pk를 그대로
    # 쓰면 어느 테이블 것인지 섞일 위험이 있다. 1부터 다시 매긴 임시 id로 분리한다.
    candidates = []
    for temp_id, obj in enumerate(pool, start=1):
        candidates.append({"temp_id": temp_id, "title": obj.title, "content": obj.content, "obj": obj})

    prev_ranking = [
        {"insight_pk": i.pk, "prev_rank": i.headliner_order, "title": i.title, "reason": ""}
        for i in prev_qs
    ]
    result = rank_headliners(
        [{"temp_id": c["temp_id"], "title": c["title"], "content": c["content"]} for c in candidates],
        prev_ranking,
    )

    by_temp_id = {c["temp_id"]: c["obj"] for c in candidates}

    picks = list(result.get("picks", []))[:HEADLINER_CAP]  # 방어적 재상한(스키마도 이미 막지만 이중 방어).
    sector_counts: dict[str, int] = {}
    accepted = []
    rejected_by_diversity = []
    for pick in picks:
        obj = by_temp_id.get(pick.get("candidate_id"))
        if obj is None:
            continue  # LLM이 존재하지 않는 candidate_id를 냈다 — 응답은 신뢰하되 검증한다.
        sector = pick.get("sector", "") or ""
        if sector not in _HEADLINER_SECTOR_PASSTHROUGH:
            count = sector_counts.get(sector, 0)
            if count >= HEADLINER_SECTOR_CAP:
                rejected_by_diversity.append((obj, sector))
                continue
            sector_counts[sector] = count + 1
        accepted.append((obj, pick))
        if len(accepted) >= HEADLINER_CAP:
            break

    # 🔴 5-2-(a) 판정 승계 되돌림 — "넷째 범주(1-A 재적용) 교체인데 새 사실(change_reason)을
    # 대지 못하면 그 교체는 제안에서 빼고 직전 순서를 유지한다." 최대 3자리라 생존자
    # (기존 확정 Insight로 직전에도 헤드라인이었던 것) 부분수열만 직전 상대 순서로
    # 되돌리는 것으로 충분하다 — 새 후보의 자리(비생존자)는 그대로 둔다.
    survivor_slots = [
        idx for idx, (obj, _pick) in enumerate(accepted)
        if isinstance(obj, Insight) and obj.pk in prev_by_pk
    ]
    if survivor_slots:
        survivors = [accepted[idx] for idx in survivor_slots]
        current_order = [obj.pk for obj, _pick in survivors]
        prev_order = sorted(current_order, key=lambda pk: prev_by_pk[pk])
        reordered = current_order != prev_order
        # change_reason이 하나라도 없는 생존자가 있으면 "말없이 뒤집었다"로 본다
        # (5-2-(a) — 뒤집는 것 자체가 아니라 사유 없이 뒤집는 것을 금지한다).
        any_unexplained = any(not pick.get("change_reason") for _obj, pick in survivors)
        if reordered and any_unexplained:
            ordered = sorted(survivors, key=lambda pair: prev_by_pk[pair[0].pk])
            for idx, pair in zip(survivor_slots, ordered):
                accepted[idx] = pair

    # 🔴 배치 단위 전량 교체(6번) — 새 RunDraft(TYPE_HEADLINER)를 만들 뿐, 기존
    # Insight.headliner_order는 여기서 건드리지 않는다. 실제 교체는 확정 시점에
    # 일어난다(2-3) — 이 함수는 어디까지나 "제안"이다.
    dropped_reasons = {d["insight_pk"]: d for d in result.get("dropped_prev_headliners", [])}
    accepted_insight_pks = {obj.pk for obj, _pick in accepted if isinstance(obj, Insight)}
    diversity_dropped_pks = {obj.pk for obj, _sector in rejected_by_diversity if isinstance(obj, Insight)}

    dropped_block = []
    with transaction.atomic():
        for rank, (obj, pick) in enumerate(accepted, start=1):
            is_existing = isinstance(obj, Insight)
            source_insight = obj if is_existing else None
            source_draft = None if is_existing else obj
            change = RunDraft.HEADLINER_CHANGE_NEW
            prev_rank = None
            change_reason = pick.get("change_reason", "") or ""
            if is_existing and obj.pk in prev_by_pk:
                prev_rank = prev_by_pk[obj.pk]
                change = (
                    RunDraft.HEADLINER_CHANGE_SAME if prev_rank == rank
                    else RunDraft.HEADLINER_CHANGE_MOVED
                )
                if change == RunDraft.HEADLINER_CHANGE_SAME:
                    change_reason = ""
            RunDraft.objects.create(
                run_job_id=run_job_id,
                draft_type=RunDraft.TYPE_HEADLINER,
                title=obj.title,
                content=pick.get("reason", ""),
                headliner_rank=rank,
                headliner_sector=pick.get("sector", "") or "",
                headliner_sector_unlisted=bool(pick.get("sector_unlisted", False)),
                headliner_change=change,
                headliner_prev_rank=prev_rank,
                headliner_change_reason=change_reason,
                headliner_source_draft=source_draft,
                headliner_source_insight=source_insight,
            )

        # 5-2 기록 의무의 나머지 절반 — 직전에 있었는데 이번에 빠진 자리. 창 밖
        # 이탈은 코드가(애초에 pool에 없었으므로 여기서 직접 판정), 중복 제외·1-A
        # 재적용은 LLM이(dropped_reasons), 다양성은 코드가(rejected_by_diversity) 채운다.
        pool_insight_pks = {c["obj"].pk for c in candidates if isinstance(c["obj"], Insight)}
        for insight in prev_qs:
            if insight.pk in accepted_insight_pks:
                continue
            if insight.pk in diversity_dropped_pks:
                sector = next(s for o, s in rejected_by_diversity if isinstance(o, Insight) and o.pk == insight.pk)
                reason = f"같은 업권({sector}) 후보가 이미 {HEADLINER_SECTOR_CAP}건이에요."
            elif insight.pk not in pool_insight_pks:
                reason = f"근거 기사가 창({window}일)을 벗어났어요." if insight.grade == Insight.GRADE_1 else "등급이 1급이 아니게 됐어요."
            elif insight.pk in dropped_reasons:
                reason = dropped_reasons[insight.pk]["reason"]
            else:
                reason = "이번 순위에서 밀려났어요."
            dropped_block.append({"prev_rank": prev_by_pk[insight.pk], "title": insight.title, "reason": reason})

    RunJob.objects.filter(pk=run_job_id).update(
        headliner_window_label=window_label, headliner_dropped=dropped_block,
    )

    usage = result.get("_usage", {})
    RunJob.objects.filter(pk=run_job_id).update(
        heartbeat_at=timezone.now(),
        input_tokens=F("input_tokens") + usage.get("input_tokens", 0),
        output_tokens=F("output_tokens") + usage.get("output_tokens", 0),
        cache_creation_input_tokens=(
            F("cache_creation_input_tokens") + usage.get("cache_creation_input_tokens", 0)
        ),
        cache_read_input_tokens=(
            F("cache_read_input_tokens") + usage.get("cache_read_input_tokens", 0)
        ),
    )


def _run_report(run_job_id: int, period_type: str) -> None:
    """SET-010 조사 축 4단계(주간 보고서)·5단계(월간 보고서) — docs/planning.md
    "3~5단계를 LLM으로 옮기는 설계"가 정본. _run_insight()와 같은 구조다(배치 전체
    1호출, 이어하기 없음, 부분 저장 없음) — 대상이 News가 아니라 대상 기간의 Insight일
    뿐이다.

    🔴 대상 기간은 services/report_periods.py의 target_week()/target_month() 단
    하나로 계산한다 — apps/setting/views.py의 버튼 잠금(_weekly_job_context(),
    _monthly_job_context())이 같은 함수를 쓴다(설계 2-1-(d) "뷰가 날짜를 따로 계산하지
    않는다"). 대상 0건 판정도 같은 문서의 insights_in_period()를 그대로 쓴다 — 잠금이
    세는 이슈와 LLM이 보는 이슈가 어긋나면 "이슈가 있다는데 빈 보고서가 나온다"가 된다.

    🔴 제목은 코드가 서식으로 만든다(weekly_title()/monthly_title()) — LLM 응답에는
    제목이 없다(설계 8-(C)).

    🔴 근거 기사(RunDraft.news)는 응답 content에 실제로 박힌 `참고: <uid>` 규약 줄의
    합집합으로 정한다 — apps/reports/templatetags/report_extras.py의 report_issues()를
    그대로 재사용한다(REPORT-002 렌더링과 같은 파서). 두 벌을 만들지 않는 이유는
    "모든 이슈 블록 참고: 줄에 적힌 uid의 합집합 = Report.news 집합"이 이미 확정된
    무결성 규약이기 때문이다 — 파서를 따로 만들면 그 규약이 파서 두 개 사이에서
    어긋날 수 있다."""
    from apps.news.models import News
    from apps.setting.models import RunDraft
    from services.llm import (
        PROMPT_VERSION_MONTHLY, PROMPT_VERSION_WEEKLY,
        generate_monthly_report, generate_weekly_report,
    )
    from services.report_periods import (
        insights_in_period, monthly_title, target_month, target_week, weekly_title,
    )

    today = timezone.localtime(timezone.now()).date()
    if period_type == "weekly":
        date_from, date_to = target_week(today)
        generate, title_fn, prompt_version = generate_weekly_report, weekly_title, PROMPT_VERSION_WEEKLY
        draft_type = RunDraft.TYPE_WEEKLY
    else:
        date_from, date_to = target_month(today)
        generate, title_fn, prompt_version = generate_monthly_report, monthly_title, PROMPT_VERSION_MONTHLY
        draft_type = RunDraft.TYPE_MONTHLY

    targets = list(
        insights_in_period(date_from, date_to).prefetch_related("news").order_by("pk")
    )
    RunJob.objects.filter(pk=run_job_id).update(
        target_count=len(targets), prompt_version=prompt_version,
    )
    if not targets:
        # 대상 0건 — 화면 잠금(views.py _weekly_job_context()/_monthly_job_context())이
        # 이 상태를 막는 정상 경로이지만, 관리 명령 등으로 직접 불렸을 때를 대비해
        # 방어적으로 그대로 완료 처리한다(_run_insight()와 같은 판단).
        return

    result = generate(targets)

    from apps.reports.templatetags.report_extras import report_issues

    with transaction.atomic():
        draft = RunDraft.objects.create(
            run_job_id=run_job_id,
            draft_type=draft_type,
            title=title_fn(date_from, date_to),
            content=result["content"],
            overview=result["overview"],
            date_from=date_from,
            date_to=date_to,
            # 🔴 2026-09-17 신설 — 축약본 문장 번호("RA 손 작업을 전부 단계 안으로
            # 넣는다" 4번, 3번과 같은 방식). Report.content_short는 확정 시점에
            # build_short_field()로 만든다(_confirm_report_drafts()).
            content_keep=result.get("content_keep", []),
        )
        news_uids = set()
        for issue in report_issues(result["content"])["issues"]:
            news_uids.update(n.uid for n in issue["news_list"])
        matched = News.objects.filter(uid__in=news_uids) if news_uids else News.objects.none()
        draft.news.set(matched)

    usage = result.get("_usage", {})
    RunJob.objects.filter(pk=run_job_id).update(
        processed_count=len(targets), heartbeat_at=timezone.now(),
        input_tokens=F("input_tokens") + usage.get("input_tokens", 0),
        output_tokens=F("output_tokens") + usage.get("output_tokens", 0),
        cache_creation_input_tokens=(
            F("cache_creation_input_tokens") + usage.get("cache_creation_input_tokens", 0)
        ),
        cache_read_input_tokens=(
            F("cache_read_input_tokens") + usage.get("cache_read_input_tokens", 0)
        ),
    )


def _run_weekly(run_job_id: int) -> None:
    _run_report(run_job_id, "weekly")


def _run_monthly(run_job_id: int) -> None:
    _run_report(run_job_id, "monthly")


def _run_newsroom_collect(run_job_id: int, newsroom_id: int) -> None:
    from apps.newsroom.models import Newsroom
    from apps.newsroom.services import collect_newsroom

    room = Newsroom.objects.get(pk=newsroom_id)
    target = room.keywords.count()
    RunJob.objects.filter(pk=run_job_id).update(target_count=target)

    # 🔴 23차 개정 — collect_naver()와 같은 계약(키워드 하나가 끝난 자리에서만 확인).
    # 🔴 2026-09-17 신설 — on_heartbeat도 collect_naver()와 같은 자리(기사 한 건마다).
    collect_newsroom(
        room, on_progress=_progress_callback(run_job_id),
        should_stop=lambda: _stop_requested(run_job_id),
        on_heartbeat=_heartbeat_callback(run_job_id),
    )


def _title_matches_newsroom_keywords(title: str, keywords) -> bool:
    """제목 키워드 검사(docs/planning.md 뉴스룸 정책 13번) — `keywords` 중 하나라도
    `title`에 부분 문자열로 들어 있으면 True. 정규화는 공백 전부 제거 + 영문 소문자
    통일까지만 한다(13-2 ③) — 가운뎃점 제거·자모 분해·유사어 확장은 하지 않는다.
    정확 일치가 아니라 포함 검사를 쓰는 이유는 한국어 조사 때문이다(13-2 ②,
    "교보생명이"·"교보증권은")."""
    def _normalize(s: str) -> str:
        return "".join(s.split()).lower()

    norm_title = _normalize(title)
    return any(_normalize(k) in norm_title for k in keywords if k)


def _run_newsroom_filter(run_job_id: int, newsroom_id: int) -> None:
    """SET-010 교보 소식 축 2단계(필터) — docs/planning.md "뉴스룸" 절 12-2가 정본.
    _run_insight()와 같은 구조(배치 전체 1호출, 이어하기 없음)이지만 두 가지가
    다르다.

    🔴 휴먼 인 더 루프가 없다(12-2 (b)) — RunProposal/RunDraft 같은 중간 그릇을
    거치지 않고 판정 결과를 NewsroomArticle에 바로 저장한다. GATED_JOB_KEYS에
    "newsroom_filter"를 넣지 않은 것과 짝을 이룬다(apps/setting/views.py) — 그래서
    이 job은 완료(STATUS_DONE)가 곧 끝이고 "확정" 단계로 가지 않는다.

    🔴 판정 기준 원문은 코드가 아니라 Newsroom.filter_prompt다(12-2 (d)) — 이
    함수가 room을 읽어 그 원문을 services/llm.py에 그대로 넘긴다. RunJob.prompt_version은
    그 원문의 해시 앞자리와 글자 수로 채운다(같은 절 "원문이 바뀌면 값도 바뀌기만
    하면 된다") — 코드 상수가 없어 cleanup/insight처럼 버전 문자열을 미리 못 박을
    수 없기 때문이다.

    🔴 2026-09-15 — LLM을 부르기 전에 제목 키워드 검사를 한 번 더 거친다(정책 13번).
    이 뉴스룸의 활성 수집 키워드(NewsroomKeyword — 계열사 NewsroomAffiliate는 보지
    않는다, 13-2 ①) 중 하나도 제목에 없는 기사는 LLM을 부르지 않고 코드가 바로
    rejected로 찍는다. 이 규칙은 LLM 필터를 대체하지 않는다 — 제목 검사를 통과한
    기사만 그 다음에 LLM이 "브리핑할 소식인가"를 다시 묻는다(13-1 (b)). 수집 코드
    (apps/newsroom/services.py)에는 넣지 않는다 — 거기 넣으면 기각된 "수집 단계에서
    버린다" 안이 된다(13-1 (a) 표).
    """
    from apps.newsroom.models import Newsroom, NewsroomArticle
    from services.llm import filter_newsroom_articles

    room = Newsroom.objects.get(pk=newsroom_id)
    targets = list(
        room.articles.filter(filter_status=NewsroomArticle.STATUS_PENDING).order_by("pk")
    )

    prompt_version = (
        f"newsroom_filter-room{room.pk}-{len(room.filter_prompt)}c-"
        f"{hashlib.sha256(room.filter_prompt.encode()).hexdigest()[:8]}"
    )
    RunJob.objects.filter(pk=run_job_id).update(
        target_count=len(targets), prompt_version=prompt_version,
    )
    if not targets:
        # 대상 0건 — 화면(_newsroom_jobs_context()의 can_run = pending_count > 0)이
        # 이 상태를 막는 정상 경로이지만, 관리 명령 등으로 직접 불렸을 때를 대비해
        # 방어적으로 그대로 완료 처리한다(_run_insight()와 같은 판단).
        return

    keywords = list(room.keywords.values_list("keyword", flat=True))
    title_rejected, llm_targets = [], []
    for article in targets:
        if _title_matches_newsroom_keywords(article.title, keywords):
            llm_targets.append(article)
        else:
            title_rejected.append(article)

    if title_rejected:
        with transaction.atomic():
            for article in title_rejected:
                article.filter_status = NewsroomArticle.STATUS_REJECTED
                article.judged_by = NewsroomArticle.JUDGED_BY_CODE_TITLE_RULE
                article.save(update_fields=["filter_status", "judged_by"])
        RunJob.objects.filter(pk=run_job_id).update(title_rejected_count=len(title_rejected))

    if not llm_targets:
        # 전부 제목 규칙에 걸렸다 — LLM을 부르지 않는다(정책 13-1 "약 88% 절감"의
        # 극단치). processed_count는 이번 배치에서 실제로 처리한 전체(=target_count)로
        # 채운다 — 뒤 코드처럼 LLM 호출 뒤에만 채우면 이 경로에서 0으로 남는다.
        RunJob.objects.filter(pk=run_job_id).update(
            processed_count=len(targets), heartbeat_at=timezone.now(),
        )
        return

    result = filter_newsroom_articles(llm_targets, room.filter_prompt)

    articles_by_id = {article.pk: article for article in llm_targets}
    with transaction.atomic():
        for item in result.get("articles", []):
            # 응답에 없는 id나 이번 배치 밖의 id는 건너뛴다 — 응답은 신뢰하되
            # 검증한다(_run_insight()의 news_ids 매칭과 같은 원칙).
            article = articles_by_id.get(item.get("id"))
            if article is None:
                continue
            passed = item.get("status") == "passed"
            article.filter_status = (
                NewsroomArticle.STATUS_PASSED if passed else NewsroomArticle.STATUS_REJECTED
            )
            article.judged_by = NewsroomArticle.JUDGED_BY_LLM
            article.summary = item.get("summary", "") if passed else ""
            rank = item.get("impact_rank") or 0
            article.impact_rank = rank if passed and rank > 0 else None
            dup_id = item.get("duplicate_of_id") or 0
            article.duplicate_of = articles_by_id.get(dup_id) if passed and dup_id else None
            article.save(update_fields=[
                "filter_status", "judged_by", "summary", "impact_rank", "duplicate_of",
            ])

    usage = result.get("_usage", {})
    RunJob.objects.filter(pk=run_job_id).update(
        # 🔴 len(targets) 그대로 — 제목 규칙으로 걸러진 건도 이번 배치에서 "처리"한
        # 것이다(LLM을 부르지 않았을 뿐 판정은 끝났다). len(llm_targets)로 좁히면
        # 진행률(processed_count)이 target_count에 못 미친 채로 "완료"가 된다.
        processed_count=len(targets), heartbeat_at=timezone.now(),
        input_tokens=F("input_tokens") + usage.get("input_tokens", 0),
        output_tokens=F("output_tokens") + usage.get("output_tokens", 0),
        cache_creation_input_tokens=(
            F("cache_creation_input_tokens") + usage.get("cache_creation_input_tokens", 0)
        ),
        cache_read_input_tokens=(
            F("cache_read_input_tokens") + usage.get("cache_read_input_tokens", 0)
        ),
    )


# docs/planning.md "뉴스룸" 절 12-3 (a) — compose_prompt의 [출력 템플릿] 마지막
# 줄이 이미 이렇게 적어 뒀다: "(통과 기사가 없을 경우 이 프롬프트를 부르지 않고,
# 코드가 '오늘은 새로운 소식이 없습니다.'를 고정 문자열로 보냅니다)". 문구를
# 재서술하지 않고 그대로 옮겼다 — 실패와 진짜 빈 날을 구분하기 위한 고정 문구라서다
# (8번 실패 설계 표 "여기서 '오늘은 새로운 소식이 없습니다'를 보내면 절대 안 된다"의
# 반대쪽, 즉 진짜 빈 날에는 이 문구를 쓰는 것이 맞다).
NEWSROOM_COMPOSE_EMPTY_BODY = "오늘은 새로운 소식이 없습니다."


def _validate_newsroom_message(body: str, target_count: int) -> list:
    """뉴스룸 3단계 코드 검증(docs/planning.md 뉴스룸 정책 12-3 (e)) — 초안을
    NewsroomMessage로 저장하기 "전"에 돈다. 발송 시점이 아니라 저장 전인 이유는
    사람이 화면(SET-009)에서 보는 문구가 검증되지 않은 것이면 안 되기 때문이다
    (사람이 승인한 것과 실제로 화면에 남는 것이 갈리면 안 된다).

    무엇을 보는지와 그 근거 — Newsroom.compose_prompt의 [출력 템플릿]을 실측해
    정했다(services/llm.py _build_newsroom_compose_system_prompt()가 그대로
    읽는 원문과 같다):
        *1. (기사 제목 1)*
        • 한 줄 요약 : ...
        • 기사 원문 링크 : <(링크 URL)|보러가기>
    ① 항목 수 — "*N. " 형태로 시작하는 볼드 번호 줄의 개수가 target_count(통과
       기사 수)와 같은지 본다. 다르면 지침 1(전수 나열)을 어긴 것이다 — LLM이
       몇 건을 조용히 빠뜨리는 실패가 8번 실패 설계 표가 명시한 대표 유형이다
       ("지침 1 위반은 LLM이 조용히 저지르는 대표적 실패라 코드가 센다").
    ② 링크 수 — "|보러가기>" 문자열의 개수가 target_count와 같은지 본다. 다르면
       지침 4(링크 필수)를 어긴 것이다. 항목 수만으로는 "항목은 다 있는데 그중
       하나에 링크가 빠졌다" 같은 개별 누락을 못 잡아 따로 센다.

    Returns:
        빈 리스트면 통과. 비어 있지 않으면 각 원소가 실패 사유 한 줄이다 — 전부
        NewsroomMessage.error에 이어 붙는다(호출부)."""
    errors = []
    item_count = len(re.findall(r"^\*\d+\.\s", body, re.MULTILINE))
    if item_count != target_count:
        errors.append(f"기사 {target_count}건인데 메시지 항목이 {item_count}개예요")
    link_count = body.count("|보러가기>")
    if link_count != target_count:
        errors.append(f"기사 {target_count}건인데 링크가 {link_count}개예요")
    return errors


def _run_newsroom_compose(run_job_id: int, newsroom_id: int) -> None:
    """SET-010 교보 소식 축 3단계(발송문) — docs/planning.md "뉴스룸" 절 12-3이
    정본. _run_newsroom_filter()와 같은 것 셋 — 배치 전체 1호출, 휴먼 인 더 루프
    없음(중간 그릇 없이 바로 저장), 판정 기준 원문을 코드가 아니라
    Newsroom.compose_prompt에서 그대로 읽는다.

    🔴 다른 것 — 저장 대상이 NewsroomArticle이 아니라 새 모델 NewsroomMessage
    (발송 레코드) 1건이다. 담을 자리가 없어(정책 12-3 (b), 실측) 이번 라운드에서
    모델을 신설했다.

    🔴 통과(passed·duplicate_of 없음) 기사가 0건이면 LLM을 부르지 않고 코드가
    고정 문구로 NewsroomMessage를 만든다(12-3 (a)) — compose_prompt의 [출력
    템플릿] 원문이 이미 그렇게 적어 두었다(위 NEWSROOM_COMPOSE_EMPTY_BODY 주석).

    🔴 코드 검증(정책 12-3 (e))은 저장 "전"에 돈다 — 걸리면 NewsroomMessage.status를
    실패로 남기되 본문은 그대로 저장한다(지우면 "지침 1을 어떻게 어겼는지"가
    사라진다). RunJob 자체는 실패로 끊지 않는다 — LLM 호출은 성공했고, 걸린 것은
    그 산출물의 구조적 완결성이라 배치 자체의 실패(인증·리전 등)와는 다른 사건이다.
    """
    from apps.newsroom.models import Newsroom, NewsroomMessage
    from services.llm import compose_newsroom_message

    room = Newsroom.objects.get(pk=newsroom_id)
    # 🔴 2026-09-17 PE 수정 — 종전에는 여기서 "통과 + 비중복" 전량을 직접 다시
    # 걸렀다. 배지(apps/setting/views.py의 _newsroom_compose_has_new_material())는
    # 09-16에 이미 "기존 모든 발송문의 포함 기사 합집합에 없는 것"으로 고쳐졌는데
    # 실행은 그대로 남아 갈렸고, 그 결과 배지는 "새 재료 없음"이라 말해도 실행을
    # 누르면 이미 보낸 기사까지 다시 담겼다(사용자가 발견한 "14건에 이전 회차까지
    # 담김" 사고). `Newsroom.compose_targets`(apps/newsroom/models.py) 하나로
    # 배지와 실행이 같은 것을 보게 한다(PM 지시 "두 벌로 짜지 말 것").
    targets = list(room.compose_targets.order_by("impact_rank", "pk"))

    prompt_version = (
        f"newsroom_compose-room{room.pk}-{len(room.compose_prompt)}c-"
        f"{hashlib.sha256(room.compose_prompt.encode()).hexdigest()[:8]}"
    )
    RunJob.objects.filter(pk=run_job_id).update(
        target_count=len(targets), prompt_version=prompt_version,
    )

    today = timezone.localtime(timezone.now()).date()

    if not targets:
        NewsroomMessage.objects.create(
            newsroom=room, date=today, body=NEWSROOM_COMPOSE_EMPTY_BODY,
            status=NewsroomMessage.STATUS_DRAFT,
        )
        RunJob.objects.filter(pk=run_job_id).update(
            processed_count=0, heartbeat_at=timezone.now(),
        )
        return

    result = compose_newsroom_message(targets, room.compose_prompt)
    body = result.get("body", "")
    errors = _validate_newsroom_message(body, len(targets))

    with transaction.atomic():
        message = NewsroomMessage.objects.create(
            newsroom=room, date=today, body=body,
            status=NewsroomMessage.STATUS_FAILED if errors else NewsroomMessage.STATUS_DRAFT,
            error="; ".join(errors),
        )
        message.articles.set(targets)

    usage = result.get("_usage", {})
    RunJob.objects.filter(pk=run_job_id).update(
        processed_count=len(targets), heartbeat_at=timezone.now(),
        input_tokens=F("input_tokens") + usage.get("input_tokens", 0),
        output_tokens=F("output_tokens") + usage.get("output_tokens", 0),
        cache_creation_input_tokens=(
            F("cache_creation_input_tokens") + usage.get("cache_creation_input_tokens", 0)
        ),
        cache_read_input_tokens=(
            F("cache_read_input_tokens") + usage.get("cache_read_input_tokens", 0)
        ),
    )


def _execute(run_job_id: int, kwargs: dict) -> None:
    """워커 스레드(start_run) 또는 호출 스레드(run_now)에서 블로킹으로 실행되는 본체.
    끝나면 RunJob을 완료 또는 실패로 바꾼다 — 확정됨으로는 절대 바꾸지 않는다(승인
    게이트는 사람이 검토 화면에서 직접 누르는 별도 뷰의 몫, 문서 4-(a)).

    🔴 PE 수정(2026-09-14) — 마지막 update()에 status=STATUS_RUNNING 조건을 건다(종전에는
    조건 없이 덮어썼다). mark_stale_running_as_stopped()가 하트비트 정지를 오판해 이 RunJob을
    먼저 중단됨으로 바꿔 버리면, 사용자가 화면에서 재실행해 새 RunJob과 새 스레드가 뜬다 —
    그런데 원래 스레드(유령)는 여전히 돌고 있다가 나중에 여기 도달해 같은 RunJob을 완료/실패로
    되돌려 쓰면, 그 사이 새로 시작된 RunJob의 진행 상태와 뒤섞여 두 스레드가 같은 작업을 동시에
    수집하는 사고로 이어진다. status=STATUS_RUNNING 조건을 걸면 이미 다른 상태로 바뀐 RunJob은
    유령 스레드가 더 이상 덮어쓰지 못한다.
    ⚠️ 조건에 안 맞아 update()가 0건이면(유령 스레드가 실제로 돌았다는 뜻) 조용히 넘어가지
    않고 반드시 logger.warning으로 남긴다 — 안 남기면 유령 스레드가 돈 사실 자체가 아무 데도
    기록되지 않는다.

    🔴 끝나면 반드시 connection.close()를 부른다(finally). Django는 요청-응답
    주기가 끝날 때 DB 커넥션을 자동으로 정리하는데, 워커 스레드는 그 주기 밖에서
    돈다 — gunicorn처럼 오래 사는 프로세스에서 이 함수가 반복 호출되면(수집을 여러
    번 누르면) 정리하지 않은 만큼 커넥션이 계속 쌓인다. run_now()는 요청 스레드
    안에서 그대로 블로킹으로 도니 이 문제가 없지만, 두 경로가 같은 함수를 쓰므로
    한 곳에서 같이 정리한다."""
    try:
        run_job = RunJob.objects.get(pk=run_job_id)
        try:
            if run_job.job_key == "collect":
                _run_collect(run_job_id, run_job.actor)
            elif run_job.job_key == "newsroom_collect":
                _run_newsroom_collect(run_job_id, kwargs["newsroom_id"])
            elif run_job.job_key == "cleanup":
                # 2026-09-14 검토 화면 + 확정 뷰 라운드에서 화면(SET-010 "실행" 버튼)이
                # 이 분기에 닿는 정상 경로가 됐다(apps/setting/views.py setting_run_start()).
                _run_cleanup(run_job_id)
            elif run_job.job_key == "insight":
                # 🔴 2026-09-15 2라운드 — IMPLEMENTED_JOB_KEYS에 "insight"가 들어오고
                # apps/setting/views.py의 setting_run_start()가 "insight" 분기와 선행
                # 잠금(_insight_block_reason())을 얻어, 이제 화면 버튼이 이 분기로 닿는
                # 정상 경로다.
                _run_insight(run_job_id)
            elif run_job.job_key == "weekly":
                # 🔴 같은 날 뒤이은 라운드 — apps/setting/views.py의 setting_run_start()가
                # "weekly" 분기와 선행 잠금(_weekly_job_context())을 얻어, 화면 버튼이
                # 이 분기로 닿는 정상 경로다.
                _run_weekly(run_job_id)
            elif run_job.job_key == "monthly":
                _run_monthly(run_job_id)
            elif run_job.job_key == "newsroom_filter":
                # 🔴 이번 라운드 — apps/setting/views.py의 setting_run_start()가
                # "newsroom_filter" 분기를 얻어, 화면 버튼이 이 분기로 닿는 정상
                # 경로다. 휴먼 인 더 루프가 없어(위 _run_newsroom_filter() docstring)
                # cleanup/insight와 달리 확정 단계 없이 여기서 판정이 끝난다.
                _run_newsroom_filter(run_job_id, kwargs["newsroom_id"])
            elif run_job.job_key == "newsroom_compose":
                # 🔴 같은 날 뒤이은 라운드 — apps/setting/views.py의 setting_run_start()가
                # "newsroom_compose" 분기를 얻어, 화면 버튼이 이 분기로 닿는 정상
                # 경로다. newsroom_filter와 같은 이유로 확정 단계 없이 여기서 끝난다.
                _run_newsroom_compose(run_job_id, kwargs["newsroom_id"])
            else:
                # 위 분기 밖의 job_key는 아직 실행 로직이 없다. 정상 경로로는 닿지
                # 않는다(관리 명령 choices, 화면은 collect/newsroom_collect/cleanup만
                # start_run을 부름). 방어적으로만 남겨 둔다.
                raise ValueError(f"실행 로직이 아직 없는 job_key입니다: {run_job.job_key}")
        except Exception:
            logger.exception(
                "RunJob %s(%s) 실행 중 처리되지 않은 예외가 발생했어요.", run_job_id, run_job.job_key,
            )
            updated = RunJob.objects.filter(pk=run_job_id, status=RunJob.STATUS_RUNNING).update(
                status=RunJob.STATUS_FAILED, finished_at=timezone.now(),
            )
            if not updated:
                logger.warning(
                    "RunJob %s(%s) 실패 처리를 건너뛰었어요 — 이미 실행중 상태가 아니었어요. "
                    "하트비트 정지 판정으로 먼저 상태가 바뀐 뒤에도 이 스레드가 계속 돈 "
                    "유령 스레드로 보여요.", run_job_id, run_job.job_key,
                )
            return

        # 🔴 23차 개정(docs/planning.md 「SET-010 실행 중단」 2번, 9-4) — 여기 도달한
        # 것은 예외 없이 정상적으로 루프가 끝났다는 뜻이고, 그것이 "끝까지 다 돌아서"인지
        # "중단 요청을 받아 일찍 멈춰서"인지는 stop_requested_at 한 칸으로만 가른다.
        # 새 STATUS_* 값을 만들지 않는다 — 사람이 멈춘 것도 STATUS_STOPPED다.
        final_status = RunJob.STATUS_STOPPED if _stop_requested(run_job_id) else RunJob.STATUS_DONE
        updated = RunJob.objects.filter(pk=run_job_id, status=RunJob.STATUS_RUNNING).update(
            status=final_status, finished_at=timezone.now(),
        )
        if not updated:
            logger.warning(
                "RunJob %s(%s) 완료/중단 처리를 건너뛰었어요 — 이미 실행중 상태가 아니었어요. "
                "하트비트 정지 판정으로 먼저 상태가 바뀐 뒤에도 이 스레드가 계속 돈"
                "유령 스레드로 보여요.", run_job_id, run_job.job_key,
            )
    finally:
        connection.close()
