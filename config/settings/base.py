from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.dashboard",
    "apps.news",
    "apps.reports",
    "apps.setting",
    "apps.graph",
    "apps.newsroom",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.dashboard.context_processors.sidebar_context",
                "apps.newsroom.context_processors.newsroom_nav",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", default="ai_market_watch"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST", default="localhost"),
        "PORT": env("DB_PORT", default="5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
# collectstatic의 수집 대상(STATICFILES_DIRS)과 수집 결과(STATIC_ROOT)는 반드시
# 다른 디렉토리여야 한다. 같으면 collectstatic이 자기 소스를 자기 자신에 다시
# 써넣으려다 "SuspiciousFileOperation" 에러로 죽는다.
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

NAVER_CLIENT_ID         = env("NAVER_CLIENT_ID", default="")
NAVER_CLIENT_SECRET     = env("NAVER_CLIENT_SECRET", default="")
NAVER_DISPLAY_PER_QUERY = env.int("NAVER_DISPLAY_PER_QUERY", default=5)
NAVER_MAX_PER_ORG       = env.int("NAVER_MAX_PER_ORG", default=8)
NAVER_REQUEST_DELAY     = env.float("NAVER_REQUEST_DELAY", default=0.25)

ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
ANTHROPIC_MODEL_FAST = env("ANTHROPIC_MODEL_FAST", default="claude-haiku-4-5-20251001")
ANTHROPIC_MODEL_SMART = env("ANTHROPIC_MODEL_SMART", default="claude-sonnet-5")

VOYAGE_API_KEY = env("VOYAGE_API_KEY", default="")
EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="voyage-multilingual-2")
EMBEDDING_SIMILARITY_THRESHOLD = env.float("EMBEDDING_SIMILARITY_THRESHOLD", default=0.82)

# Bedrock 경유 LLM 판정(docs/planning.md "1번을 LLM으로 옮기는 설계" 9번) — services/llm.py가
# AnthropicBedrock(aws_region=...)에 그대로 넘긴다. Mantle이 아니다 — 서울 리전에 엔드포인트가
# 없어 2026-09-14에 AnthropicBedrock으로 확정 검증됐다(같은 문서 「프로덕션 배포」 1-1).
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
AWS_DEFAULT_REGION = env("AWS_DEFAULT_REGION", default="ap-northeast-2")
# Bedrock 모델 ID는 직접 API의 ANTHROPIC_MODEL_FAST와 형식이 다르다("global." 접두사와
# 버전 접미사가 붙는다). 그래서 별도 키로 둔다. 1번(뉴스 정리)에만 쓴다(SMART는 3~5번 몫,
# docs/planning.md "3~5단계를 LLM으로 옮기는 설계" 7-(c)).
BEDROCK_MODEL_FAST = env(
    "BEDROCK_MODEL_FAST", default="global.anthropic.claude-haiku-4-5-20251001-v1:0",
)
# 3~5번(주요 이슈, 주간 보고서, 월간 보고서) 생성 전용. 종전 "확인 필요"였던 자리를
# 2026-09-15 PE가 실측으로 채웠다. boto3 bedrock.list_inference_profiles()로 서울
# 리전에서 "global.anthropic.claude-sonnet-5"(ACTIVE)를 확인했고, AnthropicBedrock으로
# 실제 최소 토큰 호출(max_tokens=16)까지 성공했다(응답 model="claude-sonnet-5",
# stop_reason="end_turn"). FAST와 달리 날짜와 버전 접미사("-20251001-v1:0" 같은)가 없다.
# 이 프로파일 ID 자체가 실측된 정확한 형태이며 PE가 추정해 붙인 것이 아니다.
#
# 🔴 2026-09-15 사용자 지시로 기본값을 다시 Haiku ID로 내렸다. 키는 그대로 두고 값만 바꿨다.
# 다음 사람이 판단할 수 있도록 세 가지를 남긴다.
# ① Sonnet은 서울 리전에서 실제로 동작한다(바로 위 주석). 안 되는 상태가 아니다.
# ② 그런데도 Haiku를 쓰는 이유는 비용이다(2026-09-15 사용자 지시 "무조건 비용을 아껴야 해").
# ③ 되돌리는 방법은 이 값 한 줄을 "global.anthropic.claude-sonnet-5"로 바꾸는 것뿐이다.
BEDROCK_MODEL_SMART = env(
    "BEDROCK_MODEL_SMART", default="global.anthropic.claude-haiku-4-5-20251001-v1:0",
)
