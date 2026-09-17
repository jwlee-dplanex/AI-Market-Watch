from django.contrib import admin
from django.urls import path, include
from apps.setting.views import SettingLoginView

urlpatterns = [
    path("admin/", admin.site.urls),
    # /setting/ 잠금(apps/setting/middleware.py)의 로그인 화면. SET 번호를 붙이지
    # 않는다 — 설정 메뉴 여덟 항목 밖이다(2026-09-17).
    # 🔴 auth_views.LoginView를 그대로 쓰지 않는다 — base_setting.html을 상속하는
    # 화면이라 setting_menu가 없으면 좌측 메뉴가 통째로 사라진다(templates/
    # registration/login.html PE 인계 절). SettingLoginView(apps/setting/views.py)가
    # setting_menu를 채워 내려 준다.
    # ⚠️ next_label은 걷어냈다(2026-09-17, 사용자 지시) — 「로그인하면 ○○로 이어서
    # 갈게요」 한 줄을 화면에서 지웠고 계산하던 코드도 함께 제거했다. next 파라미터
    # 자체는 그대로 쓴다. 로그인 뒤 원래 가려던 화면으로 돌아가는 동작은 살아 있고
    # 글자로 보여주지만 않는다.
    path("login/", SettingLoginView.as_view(), name="login"),
    path("", include("apps.dashboard.urls")),
    path("news/", include("apps.news.urls")),
    path("reports/", include("apps.reports.urls")),
    path("setting/", include("apps.setting.urls")),
    path("graph/", include("apps.graph.urls")),
    path("newsroom/", include("apps.newsroom.urls")),
]
