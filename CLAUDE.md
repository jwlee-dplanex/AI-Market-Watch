# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 개발 환경

- Python 3.12 가상환경: `venv/`
- PostgreSQL 16 + pgvector: Docker로 실행 (`docker-compose.yml`)
- 설정 파일: `.env` (`.env.example` 참고, `.gitignore`에 포함)

## 주요 명령어

```bash
# Docker DB 시작/중지
docker compose up -d
docker compose down

# Django 개발 서버 실행
venv\Scripts\python manage.py runserver --settings=config.settings.local

# 마이그레이션
venv\Scripts\python manage.py makemigrations --settings=config.settings.local
venv\Scripts\python manage.py migrate --settings=config.settings.local

# Django 설정 점검
venv\Scripts\python manage.py check --settings=config.settings.local

# Django shell
venv\Scripts\python manage.py shell --settings=config.settings.local
```

모든 `manage.py` 명령에 `--settings=config.settings.local`을 붙여야 합니다. `manage.py`의 기본값(`config.settings`)은 존재하지 않는 경로입니다.

## 아키텍처

서버 사이드 렌더링 중심의 Django 풀스택. 별도 API 레이어 없음.

- **HTMX** — 부분 업데이트: Django view가 HTML fragment를 반환 (JSON 최소화)
- **Alpine.js** — 클라이언트 UI 상태만 담당 (드롭다운, 토글 등)
- **pgvector** — 유사 기사 그룹핑에 코사인 유사도 사용 예정 (임계값 0.82, 그룹핑 로직 자체는 미구현)

## 프로젝트 구조

```
apps/
  dashboard/   # 전체 대시보드 (ALL-001)
  news/        # 뉴스 목록·상세 (NEWS-001, NEWS-002)
  reports/     # 보고서 목록·상세 (REPORT-001, REPORT-002)
  setting/     # 데이터소스·키워드·프롬프트·스케줄·Slack·로그 (SET-001~006)
services/
  collector.py  # 뉴스 수집 파이프라인
  llm.py        # Claude API 연동
  embedder.py   # 임베딩 생성 + 유사 기사 그룹핑
  scheduler.py  # APScheduler 작업 등록
config/settings/
  base.py       # 공통 설정 (django-environ으로 .env 로딩)
  local.py      # DEBUG=True
  production.py # DEBUG=False
templates/      # 루트 레벨 템플릿 (base.html + 앱별 하위 디렉토리)
```

각 앱의 `apps.py`에서 `name`은 반드시 `apps.xxx` 형식이어야 합니다 (예: `name = 'apps.dashboard'`).

## 설정 구조

`base.py`는 `django-environ`으로 `.env`를 로딩합니다. `BASE_DIR`은 `config/settings/base.py`에서 세 단계 위 (`Path(__file__).resolve().parent.parent.parent`)가 프로젝트 루트입니다.

## LLM 모델

| 용도 | 모델 | 설정 키 |
|------|------|---------|
| 뉴스 요약·관련성 판단 | claude-haiku-4-5-20251001 | `ANTHROPIC_MODEL_FAST` |
| 인사이트·보고서 생성 | claude-sonnet-5 | `ANTHROPIC_MODEL_SMART` |

## 화면 ID 규칙

설계 문서(`docs/design.md`)와 코드에서 화면 ID를 기준으로 소통합니다.  
`ALL-001` 대시보드 / `NEWS-001~002` 뉴스 / `REPORT-001~002` 보고서 / `SET-001~006` 설정
