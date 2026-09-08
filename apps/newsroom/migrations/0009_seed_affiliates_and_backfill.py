# 관계사 태그 시드 + 기존 128건 소급 매칭(2026-09-08, 사용자 확정).
#
# 관계사 일곱 — "교보"(그룹 전체를 가리키는 말이라 태그 대상이 아니다)는 뺀다.
# NewsroomKeyword(수집 키워드)와 이 목록은 다르다 — 교보자산신탁·디플래닉스는
# 검색하지 않지만("교보" 키워드로 들어온 기사 안에서 잡힌다) 태그는 단다.
#
# 매칭은 services/collector.py의 _find_matching_entities()를 그대로 재사용한다
# (역방향 삼킴 방지 포함) — 뉴스 조직 태깅과 같은 방식이다. 실 데이터로
# transaction.atomic() + 의도적 롤백으로 먼저 검증했고(제목+본문 매칭), 그 결과는
# 사용자가 실측한 예상치와 정확히 일치했다:
#   교보생명 39 · 교보문고 34 · SBI저축은행 23 · 교보증권 21 · 교보라이프플래닛 7 ·
#   교보자산신탁 1 · 디플래닉스 0
#   기사당 태그: 0개 13건 · 1개 107건 · 2개 6건 · 3개 2건 (128건 중 115건 태그)
#
# 등록 전 삼킴 검사(일곱 개 이름+별칭 상호 대조)도 이 검증에서 함께 실행했고
# 삼킴 쌍은 0건이었다.

from django.db import migrations

AFFILIATES = [
    ("교보생명", []),
    ("교보증권", []),
    ("교보문고", []),
    ("교보라이프플래닛", ["라이프플래닛"]),
    ("SBI저축은행", ["SBI 저축은행"]),
    ("교보자산신탁", []),
    ("디플래닉스", ["DPLANEX"]),
]


def seed_and_backfill(apps, schema_editor):
    from services.collector import _find_matching_entities

    Newsroom = apps.get_model("newsroom", "Newsroom")
    NewsroomAffiliate = apps.get_model("newsroom", "NewsroomAffiliate")
    NewsroomArticle = apps.get_model("newsroom", "NewsroomArticle")

    for room in Newsroom.objects.all():
        affiliates = [
            NewsroomAffiliate.objects.create(newsroom=room, name=name, aliases=aliases)
            for name, aliases in AFFILIATES
        ]
        for article in NewsroomArticle.objects.filter(newsroom=room):
            text = f"{article.title} {article.body}"
            article.affiliates.set(_find_matching_entities(text, affiliates))


def unseed(apps, schema_editor):
    NewsroomAffiliate = apps.get_model("newsroom", "NewsroomAffiliate")
    # CASCADE가 M2M 조인 행도 함께 지운다.
    NewsroomAffiliate.objects.filter(name__in=[name for name, _ in AFFILIATES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("newsroom", "0008_newsroomaffiliate_newsroomarticle_affiliates"),
    ]

    operations = [
        migrations.RunPython(seed_and_backfill, unseed),
    ]
