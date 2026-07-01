from django.shortcuts import render, get_object_or_404
from .models import Report


def report_list(request):
    reports = Report.objects.order_by("-date_from")
    return render(request, "reports/list.html", {"reports": reports})


def report_detail(request, uid):
    report = get_object_or_404(Report, uid=uid)
    return render(request, "reports/detail.html", {"report": report})
