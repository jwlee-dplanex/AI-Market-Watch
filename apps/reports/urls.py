from django.urls import path, register_converter
from config.converters import ShortUUIDConverter
from . import views

register_converter(ShortUUIDConverter, 'shortuuid')

urlpatterns = [
    path("", views.report_list, name="report_list"),
    path("<shortuuid:uid>/", views.report_detail, name="report_detail"),
    # 🔴 2026-09-18 신설 — 「다듬는 중」 보고서 삭제. 뷰에 @login_required가 붙어 있다
    # (/reports/는 공개 화면이라 미들웨어가 잠그지 않는다 — 뷰 독스트링 참고).
    path("<shortuuid:uid>/delete/", views.report_delete, name="report_delete"),
]
