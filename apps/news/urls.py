from django.urls import path, register_converter
from config.converters import ShortUUIDConverter
from . import views

register_converter(ShortUUIDConverter, 'shortuuid')

urlpatterns = [
    path("", views.news_list, name="news_list"),
    path("<shortuuid:uid>/", views.news_detail, name="news_detail"),
    path("<shortuuid:uid>/organizations/add/", views.news_org_add, name="news_org_add"),
    path("<shortuuid:uid>/organizations/<int:org_pk>/remove/", views.news_org_remove, name="news_org_remove"),
]
