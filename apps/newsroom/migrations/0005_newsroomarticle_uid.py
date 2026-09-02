import uuid

from django.db import migrations, models


def backfill_uid(apps, schema_editor):
    """Newsroom.uid(0004)와 같은 이유 — uuid.uuid4 콜러블 기본값은 unique 필드에
    자동 적용되지 않으므로, 이미 있는 행에는 여기서 한 번씩 새 값을 채운다. ROOM-003
    URL(/newsroom/<room_uid>/<uid>/)에 pk 대신 쓰기 위한 필드다."""
    NewsroomArticle = apps.get_model("newsroom", "NewsroomArticle")
    for article in NewsroomArticle.objects.all():
        article.uid = uuid.uuid4()
        article.save(update_fields=["uid"])


class Migration(migrations.Migration):

    dependencies = [
        ("newsroom", "0004_newsroom_uid"),
    ]

    operations = [
        migrations.AddField(
            model_name="newsroomarticle",
            name="uid",
            field=models.UUIDField(default=uuid.uuid4, null=True, db_index=True),
        ),
        migrations.RunPython(backfill_uid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="newsroomarticle",
            name="uid",
            field=models.UUIDField(default=uuid.uuid4, unique=True, db_index=True),
        ),
    ]
