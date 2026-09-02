import uuid

from django.db import migrations, models


def backfill_uid(apps, schema_editor):
    """News.uid/Report.uid와 같은 이유 — uuid.uuid4 콜러블 기본값은 unique 필드에
    자동 적용되지 않으므로(Django가 makemigrations 시 이걸 그대로 경고한다), 이미
    있는 행에는 여기서 한 번씩 새 값을 채운다. 지금은 "교보그룹" 1건뿐이다."""
    Newsroom = apps.get_model("newsroom", "Newsroom")
    for room in Newsroom.objects.all():
        room.uid = uuid.uuid4()
        room.save(update_fields=["uid"])


class Migration(migrations.Migration):

    dependencies = [
        ("newsroom", "0003_paiddomain"),
    ]

    operations = [
        migrations.AddField(
            model_name="newsroom",
            name="uid",
            field=models.UUIDField(default=uuid.uuid4, null=True, db_index=True),
        ),
        migrations.RunPython(backfill_uid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="newsroom",
            name="uid",
            field=models.UUIDField(default=uuid.uuid4, unique=True, db_index=True),
        ),
    ]
