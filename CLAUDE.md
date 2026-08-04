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
- **검증 게이트** — 뷰가 `News`를 **직접 조회할 때는 반드시 `News.objects.verified()`를 거친다**(2026-08-04 도입). RA가 관련성 판정을 마치지 않은 뉴스는 화면에 노출하지 않는다는 정책이며, 빼먹어도 에러가 나지 않고 조용히 미검증 뉴스가 노출되므로 새 조회 코드를 짤 때마다 확인해야 한다. 예외는 세 가지뿐 — `Insight.news`/`Report.news`/`OrgRelation.news`(명시 연결 M2M, 연결 자체가 검증 완료를 전제), 사이드바 "마지막 수집"(파이프라인 생존 신호), collector의 중복 체크(미검증까지 봐야 재수집을 막음). 상세는 `docs/planning.md` "검증 게이트" 절.
- **pgvector** — `Embedding` 모델·코사인 유사도 인프라는 구축돼 있으나(임계값 0.82), 현재 관련 기사 판별은 research-analyst가 배치를 직접 읽어서 수행하며 pgvector는 사용하지 않는다. 수집량 증가로 병목이 되면 PE가 상시 자동 클러스터링으로 재구현하는 걸 검토한다.

## 프로젝트 구조

```
apps/
  dashboard/   # 전체 대시보드 (ALL-001)
  news/        # 뉴스 목록·상세 (NEWS-001, NEWS-002)
  reports/     # 보고서 목록·상세 (REPORT-001, REPORT-002)
  setting/     # 데이터소스·키워드·프롬프트·스케줄·Slack·로그·기업·기술 주제 (SET-001~008)
  graph/       # 지식그래프 (GRAPH-001)
services/
  collector.py  # 뉴스 수집 파이프라인
  llm.py        # Claude API 연동
  embedder.py   # 임베딩 생성 + 유사 기사 그룹핑
  scheduler.py  # APScheduler 작업 등록
  periods.py    # 대시보드·지식그래프 공통 기간 필터 유틸
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
`ALL-001` 대시보드 / `NEWS-001~002` 뉴스 / `REPORT-001~002` 보고서 / `SET-001~008` 설정 (`SET-007` 기업 관리, `SET-008` 기술 주제 관리) / `GRAPH-001` 지식그래프

## 서브에이전트 (PM/PD/PE/RA)

`.claude/agents/`에 4개의 전담 에이전트가 정의돼 있습니다. 호출은 사용자가 "PM/PD/PE/RA 불러줘"처럼 명시적으로 요청할 때만 합니다 (자동 위임 안 함).

- **product-manager (PM)** — 기능 우선순위·정책 정의. `docs/planning.md`만 직접 수정 가능.
- **product-designer (PD)** — 화면·디자인시스템. `docs/design.md`, `templates/`만 직접 수정 가능.
- **product-engineer (PE)** — 실제 구현 전체(모델·뷰·마이그레이션·서비스 코드). 도구 제한 없음.
- **research-analyst (RA)** — 수집된 뉴스로 실제 리서치 산출물(시사점·주간보고서)을 만드는 온디맨드 운영 역할. 기업 태깅 검증·교정과 지식그래프 관계 라벨링도 정규 업무에 포함. PM/PD/PE가 "플랫폼을 만드는" 축이라면 RA는 "플랫폼을 쓰는" 축. 옵션 B 코드화 전까지는 운영 갭을 RA가 수동으로 최대한 커버하는 게 확정 원칙. 도구 제한 없음(단 `.py` 구현은 하지 않는 소프트 제약).

| 작업 유형 | 순서 |
|---|---|
| 새 화면이 있는 신규 기능 | PM → Designer → Engineer (각 단계 사이 사용자 체크포인트) |
| 화면 없는 백엔드/파이프라인 | PM → Engineer |
| UI 톤 조정 등 우선순위 판단이 불필요한 개선 | Designer → Engineer |
| 버그 수정 | Engineer만 |
| 수집 이후 노이즈 판정·삭제·태깅 교정·관련 기사 찾기·시사점·관계 라벨링·보고서 산출물 생성 | Research Analyst 단독 — 실제 데이터로 직접 판정·삭제·작성 수행 |
| 관련 기사 찾기/인사이트/보고서를 상시 자동화하는 파이프라인 구현 | PM(우선순위 판단) → Engineer(구현, RA의 수동 작업 실례 참고) |
