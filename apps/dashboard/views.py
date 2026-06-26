from django.shortcuts import render


def dashboard(request):
    context = {
        "chart_daily": [],
        "chart_category": [],
        "chart_tags": [],
    }
    return render(request, "dashboard/index.html", context)
