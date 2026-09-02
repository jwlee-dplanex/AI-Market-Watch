from django.urls import path, register_converter

from config.converters import ShortUUIDConverter

from . import views

register_converter(ShortUUIDConverter, 'shortuuid')

urlpatterns = [
    path("", views.newsroom_list, name="newsroom_list"),
    path("<shortuuid:uid>/", views.newsroom_detail, name="newsroom_detail"),
    path("<shortuuid:room_uid>/<shortuuid:uid>/", views.newsroom_article_detail, name="newsroom_article_detail"),
]
