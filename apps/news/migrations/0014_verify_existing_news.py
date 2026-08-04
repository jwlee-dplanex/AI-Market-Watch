from django.db import migrations


def verify_existing_news(apps, schema_editor):
    """검증 게이트 도입(docs/planning.md "검증 게이트: 미검증 뉴스는 화면에 노출하지 않는다"
    3번) 시점에 이미 DB에 있던 News는 전부 RA가 판정해 살아남은 것들이므로 일괄
    검증됨으로 전환한다. 검증 시각(verified_at)은 실제로 언제 검증됐는지 알 수 없으므로
    백필하지 않고 null로 남긴다 — 모르는 값을 지어내지 않는 원칙.

    이 마이그레이션은 미처리 배치가 없는 시점(RA가 직전 배치 처리를 마친 직후)에만
    실행해야 한다. 이후 신규 수집분은 필드 default(STATUS_UNVERIFIED)를 그대로 받는다.
    """
    News = apps.get_model("news", "News")
    News.objects.update(status="검증됨")


def unverify_all_news(apps, schema_editor):
    """역방향: 전부 미검증으로 되돌린다(신중히 사용 — 화면에서 전부 사라진다)."""
    News = apps.get_model("news", "News")
    News.objects.update(status="미검증")


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0013_news_status_news_verified_at"),
    ]

    operations = [
        migrations.RunPython(verify_existing_news, unverify_all_news),
    ]
