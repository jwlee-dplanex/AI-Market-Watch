from django.apps import AppConfig


class SettingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.setting"

    # ready()에 있던 scheduler.start() 호출은 2026-09-04 SET-004(스케줄 화면) 폐기와
    # 함께 제거했다(사용자 확정 — "사람이 눌러야만 돈다"). services/scheduler.py 자체를
    # 지웠으므로 여기서 부를 대상이 없다. Schedule 모델/pk=1 레코드는 과거 실측 근거로
    # 남아 있지만(apps/setting/models.py Schedule docstring 참고), 이제 이 모델을
    # 스케줄러에 등록하는 코드는 프로젝트 전체에 없다.
