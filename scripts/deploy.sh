#!/usr/bin/env bash
# EC2에서 실행하는 배포 스크립트.
#
# 2026-09-11: 「로컬(dev)과 EC2(prd)를 완전히 같게 한다」는 사용자 확정에 따라
# 앱 실행 방식이 바뀌었다 — Docker web 컨테이너가 아니라 호스트 venv +
# gunicorn(systemd 서비스 `aimarketwatch`)이다. DB만 여전히 Docker(db 서비스)다.
# manage.py 명령은 venv/bin/python으로 직접 부른다 — `source venv/bin/activate`는
# 서브셸(예: 이 스크립트가 다른 스크립트를 호출하는 경우)에서 활성화 상태가 새기
# 쉬워, 활성화 여부에 기대지 않고 인터프리터 경로를 그때그때 명시하는 쪽이 안전하다.
set -euo pipefail

cd "$(dirname "$0")/.."

# EC2 repo는 main 고정이다(develop이 아니다). 다른 브랜치에 있다면 배포 전에
# 멈춘다 — --ff-only만으로는 "브랜치를 잘못 checkout해 둔 상태"를 잡지 못한다.
current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$current_branch" != "main" ]; then
  echo "main 브랜치가 아닙니다 (현재: $current_branch) — 배포를 멈춥니다." >&2
  exit 1
fi

echo "==> git pull"
git pull --ff-only

echo "==> DB 컨테이너 기동"
docker compose up -d db

# EC2는 매일 19:00 정지, 수동 기동이라(docker-compose.yml db 서비스 주석 참고)
# db 컨테이너가 막 시작된 콜드 스타트일 수 있다. `up -d`는 컨테이너 시작만
# 보장할 뿐 Postgres가 연결을 받을 준비가 됐다는 보장은 아니므로, migrate가
# 그 사이 타이밍에 걸려 실패하지 않도록 짧게 대기한다.
echo "==> DB 준비 대기"
for i in $(seq 1 30); do
  if docker compose exec -T db pg_isready >/dev/null 2>&1; then
    echo "    DB 준비 완료"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "DB가 30초 안에 준비되지 않았습니다." >&2
    exit 1
  fi
  sleep 1
done

# requirements.txt는 전이 의존성까지 전부 ==로 고정돼 있다(2026-09-11, 로컬·EC2
# 버전 드리프트 재발 방지). 이미 동일 버전이 설치돼 있으면 pip은 네트워크 없이
# 빠르게 끝나므로, "바뀐 게 있었는지"를 스크립트가 판단하려 하지 않고 매번 돌려
# 항상 requirements.txt를 진실로 삼는다.
echo "==> 의존성 설치"
venv/bin/pip install -r requirements.txt

# 🔴 migrate보다 반드시 먼저다. 모델은 고쳤는데 마이그레이션 파일을 커밋하지
# 않은 채 배포하면, 이 체크가 없을 경우 DB 스키마가 조용히 코드보다 뒤처진다.
# 여기서 걸리면(비정상 종료) set -e가 스크립트를 즉시 멈춘다 — 마이그레이션
# 파일을 커밋하고 다시 배포한다.
echo "==> makemigrations --check (커밋 안 된 모델 변경 감지)"
venv/bin/python manage.py makemigrations --check --dry-run --settings=config.settings.production

echo "==> migrate"
venv/bin/python manage.py migrate --settings=config.settings.production

echo "==> collectstatic"
venv/bin/python manage.py collectstatic --noinput --settings=config.settings.production

# systemd 유닛과 nginx 설정은 2026-09-14부터 저장소가 정본이다(deploy/). 종전에는
# EC2에만 있어서 무엇이 적용돼 있는지 로컬에서 확인할 수 없었고 변경 이력도
# 남지 않았다. 배포마다 복사하므로, 고칠 일이 생기면 EC2를 편집하지 않고
# deploy/ 아래를 고쳐 커밋한다.
echo "==> systemd 유닛 반영"
sudo cp deploy/aimarketwatch.service /etc/systemd/system/aimarketwatch.service
sudo systemctl daemon-reload

echo "==> 앱 재기동"
sudo systemctl restart aimarketwatch

# 🔴 nginx 설정은 반영하기 전에 검사한다. 로컬에는 nginx가 없으므로(사용자 확정)
# 문법 오류를 잡는 자리가 여기뿐이다. `nginx -t`는 /etc/nginx 전체를 읽으므로
# 파일을 먼저 놓아야 검사할 수 있고, 따라서 실패 시 되돌릴 백업을 먼저 뜬다.
# 되돌리지 않으면 지금은 reload를 건너뛰어 멀쩡해 보이지만, 다음 재부팅에서
# nginx가 아예 뜨지 못한다.
NGINX_CONF=/etc/nginx/conf.d/aimarketwatch.conf

if ! command -v nginx >/dev/null 2>&1; then
  echo "nginx가 설치돼 있지 않습니다 — 'sudo dnf install -y nginx' 후 다시 배포하세요." >&2
  exit 1
fi

echo "==> nginx 설정 반영"
if [ -f "$NGINX_CONF" ]; then
  sudo cp "$NGINX_CONF" "$NGINX_CONF.bak"
fi
sudo cp deploy/nginx.conf "$NGINX_CONF"

if ! sudo nginx -t; then
  echo "nginx 설정이 유효하지 않습니다 — 이전 설정으로 되돌립니다." >&2
  if [ -f "$NGINX_CONF.bak" ]; then
    sudo mv "$NGINX_CONF.bak" "$NGINX_CONF"
  else
    sudo rm -f "$NGINX_CONF"
  fi
  exit 1
fi

# reload가 아니라 reload-or-restart다. nginx가 아직 떠 있지 않은 상태(최초 도입
# 직후나 사람이 멈춰 둔 경우)에서 `systemctl reload`는 실패하고, set -e가 배포
# 전체를 여기서 멈춘다. reload-or-restart는 떠 있으면 무중단 reload, 내려가 있으면
# start로 동작한다.
sudo systemctl reload-or-restart nginx

echo "==> 배포 완료"
sudo systemctl status aimarketwatch --no-pager
sudo systemctl status nginx --no-pager
