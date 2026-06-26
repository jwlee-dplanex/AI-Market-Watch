from django.shortcuts import render, get_object_or_404
from .models import Report


def report_list(request):
    reports = Report.objects.order_by("-year", "-week")
    return render(request, "reports/list.html", {"reports": reports})


def report_detail(request, pk):
    report = get_object_or_404(Report, pk=pk)
    return render(request, "reports/detail.html", {"report": report})
