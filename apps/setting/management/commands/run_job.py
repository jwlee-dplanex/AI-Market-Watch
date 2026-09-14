"""SET-010 실행을 터미널에서 돌리는 관리 명령.

docs/planning.md "실행 모델" 3-(f) - 웹 요청 없이 테스트와 재현이 가능해야 한다는
요구를 채운다. 로직은 services/runner.py 한 벌뿐이다 - 이 명령은 apps/setting/views.py의
setting_run_start()와 똑같이 services.runner.run_now()를 부를 뿐, 수집이나 판정 로직을
따로 갖지 않는다(두 벌이 되면 어느 쪽으로 돌렸느냐에 따라 결과가 갈린다).

사용 예:
    venv\\Scripts\\python manage.py run_job collect --settings=config.settings.local
    venv\\Scripts\\python manage.py run_job newsroom_collect --settings=config.settings.local
"""

from django.core.management.base import BaseCommand, CommandError

from apps.setting.models import RunJob
from services.runner import IMPLEMENTED_JOB_KEYS, run_now


class Command(BaseCommand):
    help = (
        "SET-010 실행을 터미널에서 돌립니다. 화면의 '실행' 버튼과 같은 로직을 "
        "웹 요청 없이 끝까지 블로킹으로 실행합니다."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "job_key",
            choices=IMPLEMENTED_JOB_KEYS,
            help="실행할 작업 키. 지금은 collect / newsroom_collect만 실제로 동작합니다.",
        )

    def handle(self, *args, **options):
        job_key = options["job_key"]
        kwargs = {}

        if job_key == "newsroom_collect":
            # apps/setting/views.py의 _target_newsroom()과 같은 "활성 채널이 1개면
            # 그것" 규칙을 그대로 따른다 - 채널 선택 로직을 여기 새로 만들지 않는다.
            from apps.setting.views import _target_newsroom
            room = _target_newsroom()
            if room is None:
                raise CommandError("수집할 채널을 하나로 정할 수 없어요(활성 채널이 0개이거나 2개 이상이에요).")
            kwargs["newsroom_id"] = room.pk

        run_job = run_now(job_key, actor=RunJob.ACTOR_COMMAND, **kwargs)
        if run_job is None:
            raise CommandError("이미 같은 작업이 진행 중이에요. 끝난 뒤 다시 실행해 주세요.")

        self.stdout.write(
            f"{job_key} 실행 결과: {run_job.status} "
            f"(처리 {run_job.processed_count}/{run_job.target_count}건, 실패 {run_job.failed_count}건)"
        )
