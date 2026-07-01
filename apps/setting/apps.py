import os
import sys
from django.apps import AppConfig

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
        scheduler.start()
