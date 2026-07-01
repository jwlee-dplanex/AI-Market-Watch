from django.urls import path, register_converter
from config.converters import ShortUUIDConverter
from . import views

register_converter(ShortUUIDConverter, 'shortuuid')

urlpatterns = [
    path("", views.report_list, name="report_list"),
    path("<shortuuid:uid>/", views.report_detail, name="report_detail"),
]
