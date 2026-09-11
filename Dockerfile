# python:3.12-slim — 로컬 venv도 3.12라 버전을 맞췄다.
# Node는 넣지 않는다: Tailwind 빌드 산출물(static/css/tailwind.css)이 이미 git에
# 커밋돼 있어(static/vendor/*.min.js도 동일) 컨테이너에서 다시 빌드할 이유가 없다.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# requirements.txt의 psycopg2-binary는 manylinux 바이너리 wheel을 쓰므로
# libpq-dev·build-essential 등 컴파일 도구가 필요 없다(확인 완료 — 아래 참고).
# ca-certificates만 있으면 된다: pip install 시 PyPI, 런타임에는 네이버 뉴스 API처럼
# 이 앱이 호출하는 외부 HTTPS 엔드포인트의 인증서 체인 검증에 쓰인다.
#
#   확인 방법: pip download psycopg2-binary --no-deps --only-binary=:all: \
#     --python-version 312 --platform manylinux_2_17_x86_64
#   → psycopg2_binary-2.9.12-cp312-cp312-manylinux2014_x86_64...whl 그대로 받아짐
#     (manylinux2014는 glibc 2.17+ 요구, Debian bookworm 기반인 이 이미지는 충족한다)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
