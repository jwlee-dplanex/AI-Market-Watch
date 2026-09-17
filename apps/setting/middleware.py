from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse


class SettingLoginRequiredMiddleware:
    """`/setting/` 경로 전체를 로그인 필수로 잠근다 (2026-09-17, 사용자 지시).

    범위는 "설정 자체에 접속 권한만 로그인으로 관리" — GET을 포함한 모든 요청이다.
    읽기·쓰기를 구분하지 않는다. SET-010 실행 화면이 3초 간격으로 폴링하는
    프래그먼트(`/setting/run/graph/`)도 이 경로 아래라 함께 잠긴다.

    설정 밖(대시보드·뉴스·보고서·지식그래프·뉴스룸)은 이 미들웨어가 보는 범위가
    아니다 — path prefix로만 판단하므로 다른 앱에는 영향이 없다.

    🔴 2026-09-17 PE 추가 — HTMX 요청(HX-Request 헤더)에는 302 대신 HX-Redirect
    헤더를 내려 준다. htmx는 자신이 보낸 XHR의 302 응답을 그대로 따라가 로그인
    페이지의 전체 HTML을 원래 스왑 대상(폴링 조각 등)에 그대로 끼워 넣어 화면이
    깨진다. HX-Redirect는 htmx에게 "이 URL로 완전한 페이지 이동을 하라"고 지시해
    브라우저 주소창이 실제로 이동하게 만든다 — redirect_to_login()이 만드는
    next 파라미터 포함 URL을 그대로 재사용하므로 이동 후 next 복귀도 동일하게
    동작한다.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/setting/") and not request.user.is_authenticated:
            login_redirect = redirect_to_login(request.get_full_path())
            if request.headers.get("HX-Request") == "true":
                response = HttpResponse()
                response["HX-Redirect"] = login_redirect.url
                return response
            return login_redirect
        return self.get_response(request)
