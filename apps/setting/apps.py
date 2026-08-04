import logging
import os
import sys
from django.apps import AppConfig

logger = logging.getLogger(__name__)

SKIP_CMDS = {"migrate", "makemigrations", "test", "collectstatic", "check", "shell", "createsuperuser"}


class SettingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.setting"

    def ready(self):
        if SKIP_CMDS & set(sys.argv):
            return
        if "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true":
            return
        from services import scheduler

        # ready()에서 던진 예외는 Django 프로세스 기동 자체를 실패시킨다 — 스케줄 등록이 실패해도
        # 서버는 떠야 하고, 실패 사실은 로그로 드러나야 한다(PM 지시 "start()의 try/except: pass
        # 제거"의 취지는 "삼키지 말라"이지 "죽으라"가 아니다. start() 내부에서 개별 스케줄 등록
        # 실패는 이미 로그로 드러내고 계속 진행하지만, DB 연결 실패 등 start() 자체가 던질 수 있는
        # 예상 밖의 예외까지 여기서 한 번 더 막아 서버 기동을 지킨다).
        try:
            scheduler.start()
        except Exception:
            logger.exception("스케줄러 기동 실패 — 이번 프로세스에서는 스케줄이 등록되지 않았습니다.")
