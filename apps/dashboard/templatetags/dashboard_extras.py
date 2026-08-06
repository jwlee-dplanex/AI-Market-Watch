from django import template

from apps.dashboard.tooltips import INFO_TOOLTIP_STEPS, INFO_TOOLTIPS

register = template.Library()


@register.inclusion_tag("components/_info_tooltip.html")
def info_tooltip(key, label, trigger_text=None):
    """카드/섹션 제목 옆에 붙는 "Info Tooltip" 팝오버를 렌더링한다.

    docs/design.md "1.5 컴포넌트 정의 › Info Tooltip" 참고. 문구는 이 태그가 아니라
    apps/dashboard/tooltips.py의 INFO_TOOLTIPS 딕셔너리에서만 관리한다(재사용 시 문구만
    딕셔너리에 추가하면 되도록).

    Args:
        key: INFO_TOOLTIPS 딕셔너리 키 (예: "dashboard.trend").
        label: 트리거 버튼 aria-label에 쓰이는 안내 대상 이름(딕셔너리 문구와는 별개).
        trigger_text: 선택. 주면 "?" 아이콘 대신 이 텍스트 자체가 트리거가 된다
            (2026-08-06 사용자 요청 — "금융사/보험사/AI 단어 자체에 호버하면 뜨게").
            안 주면 종전대로 아이콘 모드다.

    ⚠️ 단계 목록(steps)은 인자로 받지 않고 key로 조회한다. 문구를 템플릿에
    하드코딩하지 않는다는 이 컴포넌트의 원칙을 단계에도 똑같이 적용하기 위함이다.
    """
    return {
        "text": INFO_TOOLTIPS.get(key, ""),
        "label": label,
        "trigger_text": trigger_text,
        "steps": INFO_TOOLTIP_STEPS.get(key, []),
    }
