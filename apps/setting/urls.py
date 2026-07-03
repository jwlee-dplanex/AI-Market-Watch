from django.urls import path
from . import views

urlpatterns = [
    path("sources/", views.sources, name="setting_sources"),
    path("sources/<int:pk>/toggle/", views.source_toggle, name="setting_source_toggle"),
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
    path("remap/", views.remap_now, name="setting_remap_now"),
    path("schedule/save/", views.schedule_save, name="setting_schedule_save"),
    path("schedule/<int:pk>/toggle/", views.schedule_toggle, name="setting_schedule_toggle"),
    path("schedule/<int:pk>/delete/", views.schedule_delete, name="setting_schedule_delete"),
]
