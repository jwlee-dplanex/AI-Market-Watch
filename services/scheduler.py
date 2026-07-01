from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.utils import timezone

_scheduler = BackgroundScheduler(timezone="Asia/Seoul")


def _job_collect(schedule_id: int):
    from apps.setting.models import Schedule, CollectionLog
    from services.collector import collect_naver
    started_at = timezone.now()
    result = collect_naver()
    CollectionLog.objects.create(
        source=None,
        started_at=started_at,
        collected_count=result["collected"],
        status="fail" if result["errors"] else "success",
        error_message="\n".join(result["errors"]) or None,
    )
    Schedule.objects.filter(pk=schedule_id).update(last_run_at=timezone.now())
    _update_next_run(schedule_id)


def _update_next_run(schedule_id: int):
    job = _scheduler.get_job(f"schedule_{schedule_id}")
    if job and job.next_run_time:
        from apps.setting.models import Schedule
        Schedule.objects.filter(pk=schedule_id).update(next_run_at=job.next_run_time)


def register(schedule) -> None:
    job_id = f"schedule_{schedule.pk}"
    trigger = CronTrigger.from_crontab(schedule.cron_expr, timezone="Asia/Seoul")
    _scheduler.add_job(
        _job_collect, trigger,
        id=job_id, args=[schedule.pk],
        replace_existing=True,
        misfire_grace_time=300,
    )
    _update_next_run(schedule.pk)


def unregister(schedule_id: int) -> None:
    job_id = f"schedule_{schedule_id}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)


def start() -> None:
    try:
        from apps.setting.models import Schedule
        for sched in Schedule.objects.filter(is_active=True):
            try:
                register(sched)
            except Exception:
                pass
    except Exception:
        pass
    if not _scheduler.running:
        _scheduler.start()
