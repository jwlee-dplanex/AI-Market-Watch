# AI Market Watch

DPLANEX 전략기획팀을 위한 내부 리서치 자산 플랫폼입니다. 국내 금융권(은행·보험사)의 AI/AX 도입 동향과 해외 AI 기업 동향을 자동으로 수집·정리해서, 일회성 리서치가 아니라 누적되는 정보 자산을 만드는 것이 목적입니다.

## 무엇을 하는 서비스인가

- **자동 수집** — 평일 오전 9시, Naver News API 등에서 AI/AX 관련 키워드로 뉴스를 자동 수집합니다.
- **사람이 정제·집필** — 수집은 자동이지만, 노이즈 판정·삭제·이슈 그룹핑·시사점 작성·주간 보고서 편집은 리서치 담당자가 온디맨드로 직접 수행합니다(자동 분류·요약 없음 — 모든 콘텐츠는 실제 수집 기사에 근거해야 하며 날조 금지가 최우선 원칙입니다).
- **대시보드로 한눈에** — 기간별(전체/최근 30일/최근 7일) 뉴스 추이, 기업별·기술주제별 언급 순위, 주요 이슈(Insight), 기업 간 관계망(지식그래프)을 대시보드에서 확인합니다.

## 기술 스택

- **Backend**: Django 5.2 (서버 사이드 렌더링, 별도 API 레이어 없음)
- **Frontend**: HTMX(부분 업데이트) + Alpine.js(클라이언트 UI 상태) + Tailwind CSS
- **DB**: PostgreSQL 16 + pgvector (Docker)
- **외부 연동**: Naver News API, OpenDART API, Claude API(Anthropic), Voyage AI(임베딩), Slack Webhook
- **스케줄링**: APScheduler (in-process, `runserver`와 함께 기동)
- **시각화**: D3.js(지식그래프), 순수 SVG(대시보드 차트)

## 화면 구성

| 화면 ID | 내용 |
|---|---|
| `ALL-001` | 전체 대시보드 — 핵심 지표(일별 추이·기업/기술주제 랭킹), 주요 이슈, 최신 뉴스 |
| `NEWS-001~002` | 뉴스 목록·상세 |
| `REPORT-001~002` | 보고서 목록·상세 (마크다운 렌더링) |
| `SET-001~008` | 설정 — 데이터소스·키워드·프롬프트·스케줄·Slack·로그·기업·기술 주제 관리 |
| `GRAPH-001` | 지식그래프 — 기업(금융사/보험사) × AI 기업 간 공동 언급 관계망 |

화면 ID 체계와 전체 아키텍처 규칙은 [`CLAUDE.md`](./CLAUDE.md)를 참고하세요.

## 시작하기

### 사전 준비
- Python 3.12
- Docker (PostgreSQL 16 + pgvector 실행용)
- `.env` 파일 (`.env.example` 참고 — Naver/OpenDART/Anthropic/Voyage/Slack API 키 필요)

### 설치 및 실행

```bash
# 1. 가상환경 생성 및 패키지 설치
python -m venv venv
venv\Scripts\pip install -r requirements.txt   # Windows
# venv/bin/pip install -r requirements.txt      # macOS/Linux

# 2. .env 파일 생성
copy .env.example .env   # Windows
# cp .env.example .env    # macOS/Linux
# 이후 .env를 열어 실제 API 키·DB 정보를 채워 넣습니다.

# 3. DB 컨테이너 시작
docker compose up -d

# 4. 마이그레이션
venv\Scripts\python manage.py migrate --settings=config.settings.local

# 5. 개발 서버 실행
venv\Scripts\python manage.py runserver --settings=config.settings.local
```

`http://127.0.0.1:8000/`에서 확인할 수 있습니다.

모든 `manage.py` 명령에는 `--settings=config.settings.local`을 붙여야 합니다(기본값은 존재하지 않는 경로입니다).

## 프로젝트 구조

```
apps/
  dashboard/   # 전체 대시보드 (ALL-001)
  news/        # 뉴스 목록·상세 (NEWS-001~002)
  reports/     # 보고서 목록·상세 (REPORT-001~002)
  setting/     # 데이터소스·키워드·프롬프트·스케줄·Slack·로그·기업·기술 주제 (SET-001~008)
  graph/       # 지식그래프 (GRAPH-001)
services/
  collector.py  # 뉴스 수집 파이프라인
  llm.py        # Claude API 연동
  embedder.py   # 임베딩 생성 (Voyage AI)
  scheduler.py  # APScheduler 작업 등록
config/settings/
  base.py / local.py / production.py
templates/      # 앱별 하위 디렉토리를 포함한 루트 레벨 템플릿
```

## Claude Code 서브에이전트 (PM/PD/PE/RA)

이 프로젝트는 `.claude/agents/`에 정의된 4개의 전담 서브에이전트로 개발·운영됩니다. 호출은 사용자가 "PM/PD/PE/RA 불러줘"처럼 명시적으로 요청할 때만 이뤄지며, 자동으로 위임되지 않습니다.

| 에이전트 | 역할 | 직접 수정 가능 범위 |
|---|---|---|
| **product-manager (PM)** | 기능 우선순위·제품 정책 정의(예: 뉴스 관련성 판단 기준, Insight 승격 기준). 화면 ID 필요 여부 판단 | `docs/planning.md` |
| **product-designer (PD)** | 화면·디자인 시스템(컬러 토큰, 컴포넌트 패턴), 와이어프레임 설계 | `docs/design.md`, `templates/` |
| **product-engineer (PE)** | 실제 구현 전체 — 모델·뷰·마이그레이션·서비스 코드, PM/PD가 정한 요구사항 구현 | 제한 없음 |
| **research-analyst (RA)** | 수집된 뉴스로 실제 리서치 산출물(노이즈 정리·시사점·주간 보고서) 생성. PM/PD/PE가 "플랫폼을 만드는" 축이라면 RA는 "플랫폼을 쓰는" 축 | 제한 없음(단 `.py` 구현은 소프트 제약) |

작업 유형별 호출 순서(신규 화면: PM→PD→PE, 버그 수정: PE만 등)를 포함한 전체 규칙은 [`CLAUDE.md`](./CLAUDE.md#서브에이전트-pmpdpera)를 참고하세요.

## 더 알아보기

- [`CLAUDE.md`](./CLAUDE.md) — 아키텍처 규칙, 화면 ID 체계, 서브에이전트(PM/PD/PE/RA) 워크플로우
- [`docs/planning.md`](./docs/planning.md) — 제품 비전과 정책(관련성 판단 기준, Insight 승격 기준 등)
- [`docs/design.md`](./docs/design.md) — 화면별 와이어프레임과 컴포넌트 스펙
- [`docs/dev.md`](./docs/dev.md) — 데이터 모델, URL 구조 등 기술 구현 현황
