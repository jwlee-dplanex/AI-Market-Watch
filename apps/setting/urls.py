from django.urls import path
from . import views

urlpatterns = [
    path("sources/", views.sources, name="setting_sources"),
    path("keywords/", views.keywords, name="setting_keywords"),
    path("keywords/add/", views.keyword_add, name="setting_keyword_add"),
    path("keywords/<int:pk>/delete/", views.keyword_delete, name="setting_keyword_delete"),
    path("prompts/", views.prompts, name="setting_prompts"),
    path("schedule/", views.schedule, name="setting_schedule"),
    path("slack/", views.slack, name="setting_slack"),
    path("logs/", views.logs, name="setting_logs"),
    path("organizations/", views.organizations, name="setting_organizations"),
    path("organizations/save/", views.organization_save, name="setting_organization_save"),
    path("organizations/<int:pk>/toggle/", views.organization_toggle, name="setting_organization_toggle"),
]
