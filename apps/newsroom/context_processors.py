from django.urls import reverse

from .models import Newsroom


def newsroom_nav(request):
    """사이드바 「교보 소식」 항목의 라벨/링크(templates/base.html "PE 인계" 절 계약).

    PM 정책(2026-09-04): 활성 뉴스룸이 1개면 그 뉴스룸(ROOM-002)으로 직행하고
    라벨도 그 이름을 쓴다. 2개 이상이면 목록(ROOM-001)으로 돌아오고 라벨은 총칭
    "소식"이다. apps/newsroom/views.py의 newsroom_list() 리다이렉트와 같은 조건을
    쓴다 — 컨텍스트 프로세서는 사이드바 링크를, 뷰 리다이렉트는 ROOM-001 URL을 직접
    치거나 북마크로 들어온 경우를 막는다(둘은 대체재가 아니라 보완재, design.md 참고).
    """
    active_rooms = list(Newsroom.objects.filter(is_active=True).order_by("name"))
    if len(active_rooms) == 1:
        room = active_rooms[0]
        return {"newsroom_nav": {
            "label": room.name,
            "url": reverse("newsroom_detail", args=[room.uid]),
            "mode": "single",
        }}
    return {"newsroom_nav": {
        "label": "소식",
        "url": reverse("newsroom_list"),
        "mode": "multi",
    }}
