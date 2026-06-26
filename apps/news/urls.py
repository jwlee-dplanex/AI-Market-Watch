from django.urls import path
from . import views

urlpatterns = [
    path("", views.news_list, name="news_list"),
    path("<int:pk>/", views.news_detail, name="news_detail"),
    path("<int:pk>/organizations/add/", views.news_org_add, name="news_org_add"),
    path("<int:pk>/organizations/<int:org_pk>/remove/", views.news_org_remove, name="news_org_remove"),
]
