#!/usr/bin/env bash
# EC2에서 실행하는 배포 스크립트.
#
# 호스트(Amazon Linux)에는 Python 환경을 따로 두지 않는다 — manage.py 명령은
# 전부 `docker compose run`으로 web 이미지 안에서 돌린다. 호스트에 필요한 건
# git·docker·docker compose뿐이다.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> git pull"
git pull --ff-only

echo "==> web 이미지 빌드 (아래 검증은 전부 이 새 이미지 기준으로 돈다)"
docker compose build web

# 🔴 migrate보다 반드시 먼저다. 모델은 고쳤는데 마이그레이션 파일을 커밋하지
# 않은 채 배포하면, 이 체크가 없을 경우 DB 스키마가 조용히 코드보다 뒤처진다.
# 여기서 걸리면(비정상 종료) set -e가 스크립트를 즉시 멈춘다 — 마이그레이션
# 파일을 커밋하고 다시 배포한다.
echo "==> makemigrations --check (커밋 안 된 모델 변경 감지)"
docker compose run --rm web python manage.py makemigrations --check --dry-run --settings=config.settings.production

echo "==> migrate"
docker compose run --rm web python manage.py migrate --settings=config.settings.production

echo "==> collectstatic"
docker compose run --rm web python manage.py collectstatic --noinput --settings=config.settings.production

# db는 이미지 태그가 바뀌지 않으므로 그대로 유지되고, web만 새 이미지로 재기동된다.
echo "==> web 재기동"
docker compose up -d

echo "==> 배포 완료"
docker compose ps
