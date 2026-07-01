import uuid
import django.db.models.deletion
from django.db import migrations, models


def populate_news_uid(apps, schema_editor):
    News = apps.get_model("news", "News")
    for news in News.objects.filter(uid__isnull=True):
        news.uid = uuid.uuid4()
        news.save(update_fields=["uid"])


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0002_news_organizations"),
    ]

    operations = [
        # 1단계: nullable로 추가
        migrations.AddField(
            model_name="news",
            name="uid",
            field=models.UUIDField(null=True, blank=True),
        ),
        # 2단계: 기존 rows에 UUID 채우기
        migrations.RunPython(populate_news_uid, migrations.RunPython.noop),
        # 3단계: unique + not null 제약 추가
        migrations.AlterField(
            model_name="news",
            name="uid",
            field=models.UUIDField(default=uuid.uuid4, unique=True, db_index=True),
        ),
    ]
