# 뉴스룸 관계사 키워드 5개 추가 + 이름 변경(2026-09-04, 사용자 지시).
# ⚠️ 화면 문구만 "계열사"→"관계사"로 바뀌었다(2026-09-04 재수정). 파일명·변수명
# (AFFILIATE_KEYWORDS)은 PD 계약과 맞춰 영어 affiliate 그대로 둔다.
#
# display=10인 이유: 관계사 키워드의 통과율(filter_status 기준) 실측이 아직 하나도
# 없어서다. 기존 "교보"(display=20)는 그대로 둔다 — 이번 라운드는 소급 관측 구간을
# 확보하는 게 목적이라, 늦게 추가하면 그만큼 관측 구간이 통째로 날아간다(PM 판단).
#
# 이름 변경(Newsroom.name "교보그룹" → "교보 소식", description 비움)도 같은 라운드에서
# 함께 처리한다 — 별도 마이그레이션으로 쪼개지 않는 이유는 둘 다 이번 라운드 한 번의
# 사용자 지시에서 나온 같은 작업 단위이기 때문이다.

from django.db import migrations

AFFILIATE_KEYWORDS = ["교보생명", "교보증권", "교보문고", "라이프플래닛", "SBI저축은행"]

OLD_NAME = "교보그룹"
NEW_NAME = "교보 소식"


def seed(apps, schema_editor):
    Newsroom = apps.get_model("newsroom", "Newsroom")
    NewsroomKeyword = apps.get_model("newsroom", "NewsroomKeyword")

    room = Newsroom.objects.filter(name=OLD_NAME).first() or Newsroom.objects.filter(name=NEW_NAME).first()
    if not room:
        return

    room.name = NEW_NAME
    room.description = ""
    room.save(update_fields=["name", "description"])

    for keyword in AFFILIATE_KEYWORDS:
        NewsroomKeyword.objects.get_or_create(
            newsroom=room, keyword=keyword,
            defaults={"sort": "date", "display": 10},
        )


def unseed(apps, schema_editor):
    Newsroom = apps.get_model("newsroom", "Newsroom")
    NewsroomKeyword = apps.get_model("newsroom", "NewsroomKeyword")

    room = Newsroom.objects.filter(name=NEW_NAME).first()
    if not room:
        return

    NewsroomKeyword.objects.filter(newsroom=room, keyword__in=AFFILIATE_KEYWORDS).delete()
    room.name = OLD_NAME
    room.save(update_fields=["name"])


class Migration(migrations.Migration):

    dependencies = [
        ("newsroom", "0006_newsroomarticle_is_ai_related_and_more"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
