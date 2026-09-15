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

import logging
import threading
from datetime import timedelta

from django.db import IntegrityError, connection, transaction
from django.db.models import F
from django.utils import timezone

from apps.setting.models import CollectionLog, Keyword, RunJob

logger = logging.getLogger(__name__)

# 화면·manage.py run_job 명령이 실제로 열어 두는 job_key만 여기 나열한다. 관리 명령의
# choices가 이 목록 하나를 본다.
#
# 🔴 "cleanup"은 2026-09-14 2라운드에서 _run_cleanup()이 구현됐고, 이번(검토 화면 +
# 확정 뷰) 라운드에서 apps/setting/views.py의 setting_run_start()가 "cleanup" 분기를
# 얻어 버튼이 실제로 열렸다 — 그래서 여기 함께 넣는다. 확정 경로(승인 게이트) 없이
# 버튼만 열면 사람이 판정을 쌓아 놓고 확정할 자리가 없어지므로, 검토 화면과 확정 뷰가
# 먼저 갖춰진 뒤에 이 목록에 추가한 것이다.
IMPLEMENTED_JOB_KEYS = ("collect", "newsroom_collect", "cleanup")

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
# 오판하지 않을 값으로 180초(3분)를 택한다 — 실측 최댓값의 약 50배 여유이자, 흔한
# 헬스체크 타임아웃 관례(수 분)와도 맞는다.
HEARTBEAT_STALE_SECONDS = 180


def mark_stale_running_as_stopped() -> int:
    """하트비트가 끊긴 지 오래된 진행중 RunJob을 중단됨으로 표시한다. 감시 프로세스를
    따로 두지 않고, 화면을 읽는 요청(apps/setting/views.py의 setting_run() 등)마다
    이 함수를 호출해 그 자리에서 판정한다(문서 3-(e)). 반환값은 중단됨으로 바뀐 건수."""
    threshold = timezone.now() - timedelta(seconds=HEARTBEAT_STALE_SECONDS)
    return RunJob.objects.filter(
        status=RunJob.STATUS_RUNNING, heartbeat_at__lt=threshold,
    ).update(status=RunJob.STATUS_STOPPED)


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


def _run_collect(run_job_id: int, actor: str) -> None:
    from services.collector import run_collection

    target = Keyword.objects.filter(keyword_type=Keyword.TYPE_COLLECT, is_active=True).count()
    RunJob.objects.filter(pk=run_job_id).update(target_count=target)

    # run_collection()의 actor는 CollectionLog.actor 값(수동(화면)/자동(스케줄))이라
    # RunJob.actor(화면/관리 명령)와 어휘가 다르다 — 스케줄이 폐기된 지금 이 실행기를
    # 거치는 모든 수집은 사람이 시킨 것이므로 기존 화면 버튼과 동일하게 ACTOR_MANUAL로
    # 남긴다. actor 인자를 그대로 두 번째 CollectionLog.actor 값으로 승격시키지 않는다
    # — 새 choices 값을 만드는 건 이번 라운드 범위 밖이다.
    run_collection(actor=CollectionLog.ACTOR_MANUAL, on_progress=_progress_callback(run_job_id))


def _save_proposals(run_job_id: int, news, result: dict) -> None:
    """판정 결과 dict(services/llm.py classify_news()의 반환값)를 RunProposal 행으로
    저장한다. 한 트랜잭션으로 묶되, 건별 판정 자체가 이미 건별 커밋 단위다(설계
    8-(a) "전부 돌고 한꺼번에 저장하지 않는다") — 여기서 만드는 여러 행(유지/삭제 1개
    + 태그 제안 N개)은 그 한 건에 딸린 하나의 판정 결과이므로 함께 묶는다.

    🔴 행은 태그마다 하나다(설계 4-(b)) — tag_corrections·unregistered_org_candidates의
    원소 각각이 별도 RunProposal 행이 된다."""
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
        for candidate in result.get("unregistered_org_candidates", []):
            RunProposal.objects.create(
                run_job_id=run_job_id, news=news, proposal_type=RunProposal.TYPE_ORG_CANDIDATE,
                target_name=candidate["name"], reason=candidate.get("reason", ""),
            )


# 구조적 실패(인증·리전·모델 ID 오류) 감지 임계값(설계 8-(d)) — 이 값만큼 연속으로
# 실패하면 RunJob을 즉시 실패로 끊는다. 개별 건 실패(rate limit·네트워크 일시 오류·
# 응답 형식 불량 등)와 구조적 실패를 예외 타입만으로 완전히 가르지 않고 "연속 횟수"로
# 감지하는 이유는, 400으로만 떨어지는 설정 오류처럼 타입으로는 안 걸러지는 구조적
# 실패도 있기 때문이다(설계 원문이 그대로 이 방식을 지시한다). 3으로 잡은 근거 —
# SDK가 rate limit·5xx·네트워크 오류를 이미 최대 2회 자동 재시도하므로, 그러고도
# 실패가 반복되면 일시적 문제가 아닐 가능성이 높다.
CLEANUP_STRUCTURAL_FAILURE_THRESHOLD = 3


def _run_cleanup(run_job_id: int) -> None:
    from apps.news.models import News
    from apps.setting.models import RunProposal
    from services.llm import PROMPT_VERSION, classify_news

    # 이어하기(설계 8-(b)) — 이미 RunProposal이 있는 News는(어느 RunJob에서 만들어졌든)
    # 대상에서 뺀다. "같은 입력에 같은 결과가 나온다는 보장이 없어 재판정하지 않는다."
    #
    # 🔴 PE 수정(2026-09-15 실측 버그) — RunProposal.news는 SET_NULL이라, 그 제안이
    # 가리키던 News가 삭제되면 news_id가 NULL로 남는다. exclude(pk__in=...)의 서브쿼리
    # 결과에 NULL이 하나라도 섞이면 SQL의 NOT IN이 모든 행을 탈락시켜(NULL과의 비교는
    # 항상 UNKNOWN) targets가 통째로 0건이 된다 — 실제로 확정 때 삭제된 기사가 생기자마자
    # 이 쿼리가 영구히 0건으로 굳었다. news__isnull=False로 서브쿼리에서 NULL을 먼저
    # 걷어낸다 — "이미 제안이 있는 News는 재판정하지 않는다"는 애초에 News가 남아 있는
    # 제안에만 의미가 있다. News가 이미 사라진 제안은 배제 대상 자체가 될 수 없다.
    targets = list(
        News.objects.filter(status=News.STATUS_UNVERIFIED)
        .exclude(pk__in=RunProposal.objects.filter(news__isnull=False).values("news_id"))
        .order_by("pk")
    )
    RunJob.objects.filter(pk=run_job_id).update(
        target_count=len(targets), prompt_version=PROMPT_VERSION,
    )

    consecutive_failures = 0
    for news in targets:
        try:
            result = classify_news(news)
        except Exception as exc:
            consecutive_failures += 1
            RunJob.objects.filter(pk=run_job_id).update(
                failed_count=F("failed_count") + 1, heartbeat_at=timezone.now(),
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
            RunJob.objects.filter(pk=run_job_id).update(
                processed_count=F("processed_count") + 1, heartbeat_at=timezone.now(),
            )


def _run_newsroom_collect(run_job_id: int, newsroom_id: int) -> None:
    from apps.newsroom.models import Newsroom
    from apps.newsroom.services import collect_newsroom

    room = Newsroom.objects.get(pk=newsroom_id)
    target = room.keywords.count()
    RunJob.objects.filter(pk=run_job_id).update(target_count=target)

    collect_newsroom(room, on_progress=_progress_callback(run_job_id))


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
            else:
                # 위 세 분기 밖의 job_key는 아직 실행 로직이 없다. 정상 경로로는 닿지
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

        updated = RunJob.objects.filter(pk=run_job_id, status=RunJob.STATUS_RUNNING).update(
            status=RunJob.STATUS_DONE, finished_at=timezone.now(),
        )
        if not updated:
            logger.warning(
                "RunJob %s(%s) 완료 처리를 건너뛰었어요 — 이미 실행중 상태가 아니었어요. "
                "하트비트 정지 판정으로 먼저 상태가 바뀐 뒤에도 이 스레드가 계속 돈"
                "유령 스레드로 보여요.", run_job_id, run_job.job_key,
            )
    finally:
        connection.close()
