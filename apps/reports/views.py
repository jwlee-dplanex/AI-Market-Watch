from django.shortcuts import render, get_object_or_404
from .models import Report

#: pill 필터가 받아들이는 값. daily는 실사용 데이터가 없어 pill 자체를 만들지 않았으므로
#: ?period_type=daily가 와도 화이트리스트를 안 타 전체로 폴백한다(오타와 동일하게 처리).
_PERIOD_TYPE_LABELS = {"weekly": "주간", "monthly": "월간"}


def report_list(request):
    all_reports = Report.objects.order_by("-date_from")

    period_type = request.GET.get("period_type", "")
    if period_type not in _PERIOD_TYPE_LABELS:
        period_type = ""

    reports = all_reports.filter(period_type=period_type) if period_type else all_reports

    context = {
        "reports": reports,
        "period_type": period_type,
        "period_type_label": _PERIOD_TYPE_LABELS.get(period_type, ""),
        # 건수는 필터와 무관하게 항상 전체 기준(all_reports)으로 센다 — pill이 "보고 있는
        # 것"과 "고를 수 있는 것"을 동시에 말하면 필터마다 숫자가 흔들려 읽을 수 없다.
        "total_count": all_reports.count(),
        "weekly_count": all_reports.filter(period_type="weekly").count(),
        "monthly_count": all_reports.filter(period_type="monthly").count(),
    }
    return render(request, "reports/list.html", context)


def report_detail(request, uid):
    report = get_object_or_404(Report, uid=uid)
    return render(request, "reports/detail.html", {"report": report})
