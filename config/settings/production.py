from .base import *

# 이 프로젝트의 프로덕션 구성은 EC2 1대 + Docker Compose 최소 구성이다
# (RDS/ALB/CloudFront/WAF 없음, 백업 없음, 인증 없음 — 전부 사용자 결정).
# 상세 근거는 docs/planning.md 「프로덕션 배포: AWS EC2 최저비용 구성」 참고.
# 그 결과 이 파일에는 통상적인 Django 프로덕션 체크리스트 중 일부러 넣지 않은
# 항목이 있다 — 아래 각 항목에 이유를 남긴다("나중에 켜야 할 것 같은데" 하고
# 무심코 켜면 서비스가 깨지는 지점들이라 이유를 지우지 않는다).

DEBUG = False

# 사내 IP만 보안그룹으로 허용하는 구성이라 실제 접속 호스트(EIP)는 EC2 인스턴스가
# 생기기 전까지 알 수 없다. default를 주지 않아 .env에 없으면 배포 전에 바로
# ImproperlyConfigured로 걸린다 — ALLOWED_HOSTS가 비어 조용히 전부 막히는 것보다
# 낫다. 인스턴스가 생기면 EC2 .env의 DJANGO_ALLOWED_HOSTS에 EIP를 채운다.
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

# 🔴 SECURE_SSL_REDIRECT / SESSION_COOKIE_SECURE / CSRF_COOKIE_SECURE는 켜지 않는다.
# 이 구성에는 ALB도 CloudFront도 없어 HTTPS 종단이 아예 없다(HTTP만 서비스한다).
# - SECURE_SSL_REDIRECT를 켜면 모든 요청을 https로 리다이렉트하는데 받아줄 https
#   리스너가 없으므로 접속 자체가 무한 리다이렉트로 죽는다.
# - *_COOKIE_SECURE를 켜면 브라우저가 Secure 쿠키를 HTTPS 연결에서만 보내므로,
#   HTTP만 있는 이 구성에서는 세션·CSRF 쿠키가 전달되지 않아 로그인 유지·폼
#   제출이 조용히 깨진다.
# 나중에 HTTPS를 실제로 얹으면(도메인 연결 등) 그때 셋을 함께 켠다 — 하나만 켜고
# 나머지를 잊으면 절반만 보호되는 상태가 된다.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# 도메인 없이 EIP로 직접 접속하므로 실제 접속 오리진을 명시해야 CSRF 검사를
# 통과한다(Django 4+는 스킴 포함을 요구). 위와 같은 이유로 스킴은 http다.
# 예: DJANGO_CSRF_TRUSTED_ORIGINS=http://13.xxx.xxx.xxx (EIP 확정 후 채운다)
# 값이 없어도 배포 자체는 막지 않도록 default=[]로 둔다 — 이건 있어야 실제
# 폼 제출(POST)이 되는 값이지, 서버가 뜨는 것을 막는 값이 아니라서다.
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# 로그는 stdout으로 모은다. gunicorn이 systemd 서비스(`aimarketwatch`)로 돌므로
# journald가 받아 가고, 아래 명령으로 본다(2026-09-11 개정).
#
#     sudo journalctl -u aimarketwatch -f
#     sudo journalctl -u aimarketwatch -n 50
#
# ⚠️ 종전 주석은 `docker compose logs -f web`이었는데, 앱을 컨테이너가 아니라
#    호스트 venv에서 돌리기로 바뀌면서 그 명령은 더 이상 없다(web 서비스 삭제됨).
#    docs/planning.md 「프로덕션 배포」 절 1-2 참고.
#
# 파일 로깅, 로그 로테이션, 중앙 수집(CloudWatch 등)은 이번 최소 구성 범위 밖이라
# 넣지 않는다 — 필요해지면 그때 추가한다. journald가 자체 로테이션을 하므로
# 디스크가 무한정 차지는 않는다.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# WhiteNoise — ALB/CloudFront/nginx가 없는 구성이라 gunicorn 단독으로 정적 파일을
# 서빙해야 한다. DEBUG=False에서는 Django의 자동 정적 서빙이 꺼지므로, 이게 없으면
# collectstatic으로 STATIC_ROOT에 모아도 실제로 내려줄 방법이 없어 CSS/JS가 전부
# 404 난다 — 이 프로젝트는 HTMX가 프론트엔드의 핵심이라 영향이 화면 전체에 미친다.
# base.py가 아니라 여기 두는 이유는 로컬은 runserver가 정적 파일을 자체 서빙해
# 필요 없기 때문이다.
MIDDLEWARE = MIDDLEWARE.copy()
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

# Manifest 계열(CompressedManifestStaticFilesStorage)이 아니라 압축만 하는
# CompressedStaticFilesStorage를 쓴다. Manifest 계열은 collectstatic 시점에
# CSS/JS 안의 `url(...)`·소스맵 참조까지 해시된 실제 파일로 존재하는지 검증하는데,
# static/vendor/lucide.min.js가 없는 lucide.min.js.map을 참조하고 있어(벤더
# 스크립트 자체의 특성, 우리 코드가 아니다) collectstatic이 매번 하드 에러로
# 죽는다(실측: `MissingFileError: ... lucide.min.js.map could not be found`).
# CDN·장기 브라우저 캐싱이 없는 이 최소 구성에서는 해시된 캐시버스팅 파일명이
# 주는 이득도 크지 않아, 검증 없는 압축 전용 저장소로 내렸다.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
