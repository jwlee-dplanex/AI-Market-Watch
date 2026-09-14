# body_is_truncated 소급 채우기(2026-09-14, 뉴스룸 정책 6-3절 (h)).
#
# 크롤 성공이면 본문이 반드시 MIN_BODY_LENGTH(200자) 이상이므로
# len(body) < 200은 크롤 실패와 동치다 — 추정이 아니라 코드가 보증하는 관계다.
# 실측(2026-09-14, NewsroomArticle 245건 전수)으로 200자 이상인데 크롤 실패로
# 의심되는 건이 없음을 확인했다(200~300자 구간 2건 모두 정상 기사 문장).
#
# 🔴 이 소급은 이데일리 메뉴 덤프 9건(398~414자)을 잡지 못한다. 그 9건은
# 크롤 "성공"으로 저장된 데이터라 이 필드의 정의(=크롤 실패로 남은 요약문
# 잔여물)에 해당하지 않는다 — 오류가 아니라 정의대로 False로 남는다.

from django.db import migrations

BODY_LENGTH_THRESHOLD = 200


def backfill(apps, schema_editor):
    NewsroomArticle = apps.get_model("newsroom", "NewsroomArticle")
    for article in NewsroomArticle.objects.all().iterator():
        is_truncated = len(article.body) < BODY_LENGTH_THRESHOLD
        if article.body_is_truncated != is_truncated:
            article.body_is_truncated = is_truncated
            article.save(update_fields=["body_is_truncated"])


def unbackfill(apps, schema_editor):
    NewsroomArticle = apps.get_model("newsroom", "NewsroomArticle")
    NewsroomArticle.objects.update(body_is_truncated=False)


class Migration(migrations.Migration):

    dependencies = [
        ("newsroom", "0010_newsroomarticle_body_is_truncated"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
