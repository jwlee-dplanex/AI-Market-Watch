from django.db import migrations, models


def migrate_context_to_collect(apps, schema_editor):
    Keyword = apps.get_model("setting", "Keyword")
    Keyword.objects.filter(keyword_type="컨텍스트").update(keyword_type="수집")


def seed_naver_datasource(apps, schema_editor):
    DataSource = apps.get_model("setting", "DataSource")
    DataSource.objects.get_or_create(
        name="Naver News API",
        defaults={
            "url": "https://openapi.naver.com/v1/search/news.json",
            "source_type": "api",
            "is_active": True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("setting", "0005_alter_keyword_keyword_type_and_more"),
    ]

    operations = [
        # 1. Keyword에 sort 필드 추가
        migrations.AddField(
            model_name="keyword",
            name="sort",
            field=models.CharField(
                choices=[("date", "최신순"), ("sim", "관련도순")],
                default="date",
                max_length=10,
            ),
        ),
        # 2. 컨텍스트 → 수집 전환
        migrations.RunPython(migrate_context_to_collect, migrations.RunPython.noop),
        # 3. keyword_type choices에서 컨텍스트 제거
        migrations.AlterField(
            model_name="keyword",
            name="keyword_type",
            field=models.CharField(
                choices=[("수집", "수집"), ("제외", "제외")],
                default="수집",
                max_length=10,
            ),
        ),
        # 4. Naver News API DataSource 초기 행 삽입
        migrations.RunPython(seed_naver_datasource, migrations.RunPython.noop),
    ]
