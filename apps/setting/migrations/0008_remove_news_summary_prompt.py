from django.db import migrations

# 0007에서 시딩한 "뉴스 요약" 프롬프트는 services/llm.py의 classify_news()/
# process_unclassified() 제거(수동 "AI 처리" 버튼 폐지, research-analyst 에이전트가
# 온디맨드로 관련성 판정을 대체)로 더 이상 참조하는 코드가 없어 데이터만 정리합니다.
# 0007 마이그레이션 자체는 이미 적용된 이력이므로 삭제하지 않고 그대로 둡니다.

PROMPT_NAME = "뉴스 요약"


def remove_prompt(apps, schema_editor):
    Prompt = apps.get_model("setting", "Prompt")
    Prompt.objects.filter(name=PROMPT_NAME).delete()


def restore_prompt(apps, schema_editor):
    # 0007의 seed_prompt와 동일한 내용으로 복원 (역방향 마이그레이션 지원용)
    Prompt = apps.get_model("setting", "Prompt")
    PROMPT_CONTENT = """당신은 국내 금융권(은행·보험사)의 AI/AX 도입 동향과 해외 AI 기업 동향을
추적하는 리서치 어시스턴트입니다.

아래 뉴스 기사를 읽고 다음을 판단하세요:

1. is_relevant: 이 기사의 핵심 주제가 다음 중 하나에 해당하면 true,
   AI/AX 관련 언급이 스치듯 나오거나 핵심 주제가 아니면 false
   - 금융사·보험사의 AI/AX 기술 도입·전략·투자
   - AI 기업(오픈AI, 앤트로픽 등)의 기술·사업·투자 동향
   - AI/AX 관련 규제·정책

2. summary: is_relevant가 true인 경우에만 2-3문장으로 핵심 내용 요약
   (false인 경우 빈 문자열)

다음 JSON 형식으로만 답하세요:
{"is_relevant": true 또는 false, "summary": "..."}

---
제목: {title}
본문: {body}"""
    Prompt.objects.get_or_create(
        name=PROMPT_NAME,
        defaults={
            "purpose": "수집된 뉴스의 관련성 판단 및 요약 (Claude Haiku)",
            "content": PROMPT_CONTENT,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("setting", "0007_seed_news_summary_prompt"),
    ]

    operations = [
        migrations.RunPython(remove_prompt, restore_prompt),
    ]
