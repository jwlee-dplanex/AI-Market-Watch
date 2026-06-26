from django.urls import path
from . import views

urlpatterns = [
    path("sources/", views.sources, name="setting_sources"),
    path("keywords/", views.keywords, name="setting_keywords"),
    path("prompts/", views.prompts, name="setting_prompts"),
    path("schedule/", views.schedule, name="setting_schedule"),
    path("slack/", views.slack, name="setting_slack"),
    path("logs/", views.logs, name="setting_logs"),
]
