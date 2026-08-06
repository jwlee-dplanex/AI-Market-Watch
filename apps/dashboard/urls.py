from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("metrics/", views.dashboard_metrics, name="dashboard_metrics"),
]
