import logging
import re

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.utils import timezone

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler(timezone="Asia/Seoul")

_DOW_NAME_RE = re.compile(r"[a-zA-Z]")


def _translate_cron_dow(token: str) -> str:
    """표준 crontab 요일 필드(0 또는 7=일요일, 1=월요일, ..., 6=토요일)를 APScheduler
    CronTrigger의 day_of_week 규칙(요일 이름은 mon..sun으로 동일하지만, 숫자는 0=월요일 ...
    6=일요일 — "The first weekday is always monday", APScheduler 공식 문서)으로 옮긴다.

    ⚠️ 실제로 발견된 버그(2026-08-04, 관측성 정책 검증 중): `CronTrigger.from_crontab()`은
    day_of_week 토큰이 숫자면 표준 crontab 규칙으로 변환하지 않고 그대로 자기 규칙에 넣는다.
    그 결과 이 프로젝트의 기존 cron_expr "0 9 * * 1-5"(표준 규칙으로는 월~금 09:00)가 실제로는
    **화~토 09:00**로 등록되고 있었다(직접 재현: `CronTrigger.from_crontab('0 9 * * 1-5', ...)`.
    get_next_fire_time을 월요일부터 순서대로 넣어 보면 월요일이 통째로 빠지고 화~토만 걸린다).
    요일 이름(mon-fri 등)을 쓰면 이 문제가 없으므로 이름 토큰은 그대로 둔다."""
    if _DOW_NAME_RE.search(token):
        return token  # 이름(mon, tue, ...)은 이미 APScheduler 규칙과 호환된다

    def shift(n: str) -> str:
        return str((int(n) % 7 - 1) % 7)  # 7(일요일 별칭)도 0으로 접고 나서 이동

    parts = []
    for piece in token.split(","):
        if piece == "*":
            parts.append(piece)
        elif "-" in piece:
            a, b = piece.split("-", 1)
            parts.append(f"{shift(a)}-{shift(b)}")
        else:
            parts.append(shift(piece))
    return ",".join(parts)


def _build_cron_trigger(cron_expr: str) -> CronTrigger:
    """표준 crontab 문자열로 CronTrigger를 만드는 단일 지점 — register()가 이 함수만 통해서
    트리거를 만든다(위 day_of_week 버그 수정을 한 곳에만 두기 위함)."""
    values = cron_expr.split()
    if len(values) == 5:
        values = list(values)
        values[4] = _translate_cron_dow(values[4])
        cron_expr = " ".join(values)
    return CronTrigger.from_crontab(cron_expr, timezone="Asia/Seoul")


# misfire 완화 정책(docs/planning.md "수집 파이프라인 관측성 정책" 4번, 2026-08-04 확정):
# "당일 안에 실행되면 그날 수집으로 인정한다. 여러 날 밀린 실행은 몰아서 여러 번 돌리지 않고
# 1회로 합친다." 예정 시각(09:00 KST)부터 그날 자정까지 최대 15시간 지연까지 유예해 "그날 중
# 아무 때나 (서버가 켜져 있는 채로) 다시 깨어나도 당일 수집으로 인정"을 만족시킨다. coalesce=True로
# 그 사이에 여러 번 놓친 실행(예: PC가 절전 모드로 몇 시간 멈춰 있던 경우)이 있어도 1회만 실행한다.
# ⚠️ 이 정책은 "서버 프로세스가 살아있는 채로 잠깐 멈췄다 깨어나는" 시나리오(절전 등)에만 유효하다.
# "서버 자체가 꺼져 있어서 그날 수집이 아예 안 되는" 시나리오는 별개다 — 이건 정상 동작으로 감수
# 하기로 확정됐고(2026-08-04, 사용자 결정), 이를 보정하는 기동 시 catch-up 기능은 도입하지 않는다.
# 근거: (a) 개발 중 autoreload마다 실제 수집이 반복 실행되는 사고로 이어졌고, (b) 상시 구동 서버로
# 전환하면(옵션 B) 서버가 꺼질 일이 없어 애초에 필요 없어지는 기능이라, 임시 환경(개발 PC)만을
# 위해 영구 코드에 훅을 심는 셈이었다.
MISFIRE_GRACE_SECONDS = 15 * 60 * 60


def _job_collect(schedule_id: int):
    from apps.setting.models import Schedule, CollectionLog
    from services.collector import run_collection
    # CollectionLog는 run_collection() 진입점 안에서 남는다(actor=자동/스케줄) — 여기서 직접
    # CollectionLog.objects.create()를 부르지 않는다(docs/planning.md "수집 파이프라인 관측성
    # 정책" 2번, 로그 책임을 호출부에 맡기지 않는 구조 결정).
    run_collection(actor=CollectionLog.ACTOR_SCHEDULED)
    # ⚠️ last_run_at은 "스케줄 실행"의 증거이므로 여기(스케줄 잡)에서만 갱신한다. collect_now
    # (수동 실행)는 스케줄 실행이 아니므로 절대 이 필드를 건드리지 않는다 — 건드리면 "스케줄이
    # 살아 있다"는 거짓 신호가 새로 생긴다(오케스트레이터 지시 사항).
    Schedule.objects.filter(pk=schedule_id).update(last_run_at=timezone.now())
    _update_next_run(schedule_id)


def _update_next_run(schedule_id: int):
    """"다음 실행"의 단일 출처 규칙(docs/planning.md "수집 파이프라인 관측성 정책" 3-(b)):
    화면의 "다음 실행"은 APScheduler 잡의 실제 다음 실행 시각만을 출처로 한다.

    - 잡이 없으면(미등록·비활성) 반드시 null로 비운다 — 모르는 걸 비워 두는 원칙(검증 게이트
      3번의 "검증 시각을 백필하지 않는다"와 동일). getattr 기본값으로도 이걸 보장한다: 스케줄러가
      아직 시작 전이라 잡이 "pending" 상태면 Job 객체엔 next_run_time 속성 자체가 없어(APScheduler
      내부 구현 — _real_add_job이 스케줄러 STOPPED 상태에선 호출되지 않아 next_run_time이 아예
      설정되지 않음) job.next_run_time 접근이 AttributeError를 던진다. 이게 바로 register()가
      _scheduler.start() 이전에 불릴 때 터졌던 실제 원인이다.
    - 갱신은 잡이 실제로 존재하는(= 스케줄러가 돌고 있어 다음 실행 시각이 계산된) 시점에만 한다.
      register()가 스케줄러 기동 전(start()의 일괄 등록 경로)에 불리면 이 함수는 호출부에서부터
      스킵되고, start()가 _scheduler.start() 이후 별도로 한 번 더 돌며 갱신한다(아래 start() 참고).
    """
    from apps.setting.models import Schedule
    job = _scheduler.get_job(f"schedule_{schedule_id}")
    next_run = getattr(job, "next_run_time", None) if job else None
    Schedule.objects.filter(pk=schedule_id).update(next_run_at=next_run)


def register(schedule) -> None:
    job_id = f"schedule_{schedule.pk}"
    trigger = _build_cron_trigger(schedule.cron_expr)
    _scheduler.add_job(
        _job_collect, trigger,
        id=job_id, args=[schedule.pk],
        replace_existing=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        coalesce=True,
    )
    # 스케줄러가 아직 시작 전이면(기동 시 start()의 일괄 등록 경로) 방금 추가한 잡은 pending 상태라
    # 다음 실행 시각이 아직 계산되지 않는다 — 여기서 갱신을 시도하지 않는다. start()가
    # _scheduler.start() 직후 활성 스케줄 전체를 한 번 더 돌며 일괄 갱신한다. 스케줄러가 이미 돌고
    # 있는 상태(화면에서 저장/토글하는 런타임 경로)라면 잡이 즉시 등록되므로 바로 갱신해도 안전하다.
    if _scheduler.running:
        _update_next_run(schedule.pk)


def unregister(schedule_id: int) -> None:
    job_id = f"schedule_{schedule_id}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
    # 잡이 사라졌으니 "다음 실행"도 함께 비운다 — 안 그러면 비활성 전환 후에도 옛 "다음 실행" 값이
    # 화면에 남아 거짓 신호가 된다(docs/planning.md "수집 파이프라인 관측성 정책" 3-(b)).
    from apps.setting.models import Schedule
    Schedule.objects.filter(pk=schedule_id).update(next_run_at=None)


def is_registered(schedule_id: int) -> bool:
    """의도(Schedule.is_active)와 실제 등록 상태를 분리해서 보여주기 위한 조회 함수
    (docs/planning.md "수집 파이프라인 관측성 정책" 3-(c)). 둘이 어긋나면 그 자체가 경보다 —
    표시 방식은 PD 몫이라 여기서는 값만 제공한다."""
    return _scheduler.get_job(f"schedule_{schedule_id}") is not None


def start() -> None:
    from apps.setting.models import Schedule
    schedules = list(Schedule.objects.filter(is_active=True))
    for sched in schedules:
        try:
            register(sched)
        except Exception:
            # (a) 실패를 조용히 삼키지 않는다 — 빈 스케줄러가 정상인 척 기동되면 안 된다
            # (docs/planning.md "수집 파이프라인 관측성 정책" 3-(a), 기존 try/except: pass 제거).
            # ⚠️ "삼키지 않는다"는 "로그로 드러낸다"는 뜻이지 "서버 기동을 멈춘다"는 뜻이 아니다 —
            # 한 스케줄 등록 실패가 서버 전체를 못 뜨게 하면 안 되므로 여기서 로그만 남기고
            # 다음 스케줄 등록을 계속한다(호출부 apps.py의 ready()도 동일한 원칙으로 이 함수
            # 전체를 한 번 더 감싼다).
            logger.exception(
                "스케줄 등록 실패 (schedule_id=%s, cron=%r) — 이 스케줄은 이번 기동에서 등록되지 않았습니다.",
                sched.pk, sched.cron_expr,
            )
    if not _scheduler.running:
        _scheduler.start()
    # register()가 스케줄러 기동 전에 불려 next_run_at을 갱신하지 못했던 항목들을, 스케줄러가 실제로
    # 도는 지금 시점에 한 번 더 돌며 채운다(위 register()/_update_next_run() 주석 참고).
    for sched in schedules:
        _update_next_run(sched.pk)
