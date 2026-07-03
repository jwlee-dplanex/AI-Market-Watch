from django.db import migrations
from pgvector.django import VectorField


class Migration(migrations.Migration):
    dependencies = [
        ("news", "0003_news_uid"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="embedding",
                    name="vector",
                    field=VectorField(dimensions=1024),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=[
                        "ALTER TABLE news_embedding DROP COLUMN IF EXISTS vector",
                        "ALTER TABLE news_embedding ADD COLUMN vector vector(1024) NOT NULL",
                    ],
                    reverse_sql=[
                        "ALTER TABLE news_embedding DROP COLUMN IF EXISTS vector",
                        "ALTER TABLE news_embedding ADD COLUMN vector vector(384) NOT NULL",
                    ],
                ),
            ],
        ),
    ]
