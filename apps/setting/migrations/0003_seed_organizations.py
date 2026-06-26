from django.db import migrations


SEED_DATA = [
    # 금융사
    {"name": "KB국민은행",   "org_type": "금융사", "aliases": ["국민은행", "KB", "KB금융"]},
    {"name": "신한은행",     "org_type": "금융사", "aliases": ["신한", "신한금융"]},
    {"name": "우리은행",     "org_type": "금융사", "aliases": ["우리", "우리금융"]},
    {"name": "하나은행",     "org_type": "금융사", "aliases": ["하나", "하나금융"]},
    {"name": "NH농협은행",   "org_type": "금융사", "aliases": ["농협", "NH", "농협은행"]},
    {"name": "카카오뱅크",   "org_type": "금융사", "aliases": ["카카오뱅크", "kakaobank"]},
    {"name": "토스뱅크",     "org_type": "금융사", "aliases": ["토스", "toss"]},
    {"name": "케이뱅크",     "org_type": "금융사", "aliases": ["케이뱅크", "k-bank"]},
    # 보험사
    {"name": "삼성생명",     "org_type": "보험사", "aliases": ["삼성생명보험"]},
    {"name": "교보생명",     "org_type": "보험사", "aliases": ["교보생명보험", "교보"]},
    {"name": "한화생명",     "org_type": "보험사", "aliases": ["한화생명보험", "한화"]},
    {"name": "현대해상",     "org_type": "보험사", "aliases": ["현대해상화재보험"]},
    {"name": "DB손해보험",   "org_type": "보험사", "aliases": ["DB손보", "동부화재"]},
    {"name": "삼성화재",     "org_type": "보험사", "aliases": ["삼성화재해상보험"]},
    # IT
    {"name": "팔란티어",     "org_type": "IT", "aliases": ["Palantir", "palantir"]},
    {"name": "데이터브릭스", "org_type": "IT", "aliases": ["Databricks", "databricks"]},
    {"name": "스노우플레이크","org_type": "IT", "aliases": ["Snowflake", "snowflake"]},
    {"name": "마이크로소프트","org_type": "IT", "aliases": ["Microsoft", "MS", "microsoft"]},
    {"name": "구글",         "org_type": "IT", "aliases": ["Google", "google", "알파벳", "Alphabet"]},
    {"name": "메타",         "org_type": "IT", "aliases": ["Meta", "meta", "페이스북", "Facebook"]},
    {"name": "세일즈포스",   "org_type": "IT", "aliases": ["Salesforce", "salesforce"]},
    {"name": "아마존",       "org_type": "IT", "aliases": ["Amazon", "AWS", "amazon"]},
    # AI
    {"name": "앤트로픽",     "org_type": "AI", "aliases": ["Anthropic", "anthropic"]},
    {"name": "오픈AI",       "org_type": "AI", "aliases": ["OpenAI", "openai"]},
    {"name": "엔비디아",     "org_type": "AI", "aliases": ["NVIDIA", "nvidia"]},
    {"name": "허깅페이스",   "org_type": "AI", "aliases": ["HuggingFace", "huggingface", "Hugging Face"]},
    {"name": "코히어",       "org_type": "AI", "aliases": ["Cohere", "cohere"]},
    {"name": "미스트랄",     "org_type": "AI", "aliases": ["Mistral", "mistral"]},
]


def seed_organizations(apps, schema_editor):
    Organization = apps.get_model("setting", "Organization")
    for data in SEED_DATA:
        Organization.objects.get_or_create(
            name=data["name"],
            defaults={"org_type": data["org_type"], "aliases": data["aliases"]},
        )


def unseed_organizations(apps, schema_editor):
    Organization = apps.get_model("setting", "Organization")
    names = [d["name"] for d in SEED_DATA]
    Organization.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("setting", "0002_organization"),
    ]

    operations = [
        migrations.RunPython(seed_organizations, unseed_organizations),
    ]
