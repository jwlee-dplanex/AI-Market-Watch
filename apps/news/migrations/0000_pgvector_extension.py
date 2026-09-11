# 지금까지 어떤 마이그레이션도 `CREATE EXTENSION vector`를 실행한 적이 없다 —
# 로컬 개발 DB는 누군가 처음에 수동으로 psql에서 만들어 둔 상태였다(문서화되지
# 않음). 그 결과 0001_initial이 Embedding 모델의 vector 컬럼을 만들 때 이미
# extension이 있다고 가정하고 있어, 완전히 새 Postgres(EC2의 새 컨테이너 등)에서
# `migrate`를 돌리면 `type "vector" does not exist`로 실패한다(실측 재현,
# 2026-09-08). 0001보다 먼저 실행돼야 하므로 0000으로 번호를 매기고
# 0001_initial의 dependencies에 추가했다.
# CreateExtension은 "CREATE EXTENSION IF NOT EXISTS"라 이미 extension이 있는
# 기존 로컬 DB에서 다시 돌아도 안전하다(idempotent).
from django.db import migrations
from pgvector.django import VectorExtension


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        VectorExtension(),
    ]
