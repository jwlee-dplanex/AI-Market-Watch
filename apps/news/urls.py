from django.urls import path
from . import views

urlpatterns = [
    path("", views.news_list, name="news_list"),
    path("<uuid:uid>/", views.news_detail, name="news_detail"),
    path("<uuid:uid>/organizations/add/", views.news_org_add, name="news_org_add"),
    path("<uuid:uid>/organizations/<int:org_pk>/remove/", views.news_org_remove, name="news_org_remove"),
]
