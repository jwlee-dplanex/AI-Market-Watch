from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.dashboard.urls")),
    path("news/", include("apps.news.urls")),
    path("reports/", include("apps.reports.urls")),
    path("setting/", include("apps.setting.urls")),
    path("graph/", include("apps.graph.urls")),
]
