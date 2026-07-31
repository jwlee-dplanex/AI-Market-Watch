from django import template

from apps.dashboard.tooltips import INFO_TOOLTIPS

register = template.Library()


@register.inclusion_tag("components/_info_tooltip.html")
def info_tooltip(key, label):
    """카드/섹션 제목 옆에 붙는 "Info Tooltip" 팝오버를 렌더링한다.

    docs/design.md "1.5 컴포넌트 정의 › Info Tooltip" 참고. 문구는 이 태그가 아니라
    apps/dashboard/tooltips.py의 INFO_TOOLTIPS 딕셔너리에서만 관리한다(재사용 시 문구만
    딕셔너리에 추가하면 되도록).

    Args:
        key: INFO_TOOLTIPS 딕셔너리 키 (예: "dashboard.trend").
        label: 트리거 버튼 aria-label에 쓰이는 안내 대상 이름(딕셔너리 문구와는 별개).
    """
    return {
        "text": INFO_TOOLTIPS.get(key, ""),
        "label": label,
    }
