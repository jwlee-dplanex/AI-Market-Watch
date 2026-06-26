from django.db import migrations


def merge_it_into_ai(apps, schema_editor):
    Organization = apps.get_model("setting", "Organization")
    Organization.objects.filter(org_type="IT").update(org_type="AI")


def split_ai_back_to_it(apps, schema_editor):
    # Reverse: restore seeded IT companies back to IT
    IT_NAMES = [
        "팔란티어", "데이터브릭스", "스노우플레이크",
        "마이크로소프트", "구글", "메타", "세일즈포스", "아마존",
    ]
    Organization = apps.get_model("setting", "Organization")
    Organization.objects.filter(name__in=IT_NAMES, org_type="AI").update(org_type="IT")


class Migration(migrations.Migration):

    dependencies = [
        ("setting", "0003_seed_organizations"),
    ]

    operations = [
        migrations.RunPython(merge_it_into_ai, split_ai_back_to_it),
    ]
