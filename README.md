# AI Market Watch

DPLANEX 전략기획팀을 위한 내부 리서치 자산 플랫폼입니다. 국내 금융권(은행·보험사)의 AI/AX 도입 동향과 그와 연결된 AI 기업 동향(금융사·보험사가 관여한 협업·도입·검토)을 자동으로 수집·정리해서, 일회성 리서치가 아니라 누적되는 정보 자산을 만드는 것이 목적입니다. (AI 기업 단독 동향은 스코프 밖입니다.)

## 무엇을 하는 서비스인가

- **수집** — Naver News API 등에서 AI/AX 관련 키워드로 뉴스를 모읍니다. **실행 방식은 환경에 따라 다릅니다** — 로컬은 설정 > 데이터소스(SET-001)의 "지금 수집"으로 사람이 직접 돌리고, 프로덕션은 평일 오전 9시 스케줄로 자동 실행합니다. 스케줄러가 `runserver` 프로세스 안에 있어서 서버가 9시에 떠 있지 않으면 그날 실행이 예약조차 되지 않기 때문입니다(자세한 내용은 [`docs/dev.md`](./docs/dev.md) 8장). **로컬에서 아침에 수집이 안 돼 있어도 버그가 아닙니다.**
- **에이전트가 정제·집필** — 수집은 자동이지만, 노이즈 판정·삭제·이슈 그룹핑·시사점 작성·주간 보고서 편집은 research-analyst(RA) 에이전트가 사용자 호출에 따라 온디맨드 세션에서 직접 수행합니다(상시 자동 분류·요약 파이프라인 없음 — 모든 콘텐츠는 실제 수집 기사에 근거해야 하며 날조 금지가 최우선 원칙입니다).
- **검증 전에는 노출하지 않음** — 수집된 뉴스는 곧바로 화면에 나타나지 않습니다. RA가 관련성 판정을 마치고 검증 완료로 전환한 뉴스만 대시보드·목록·지식그래프에 노출됩니다. 수집량의 상당수가 키워드 오탐이나 동일 사건 중복 보도라(실측 사례: 60건 중 52건), 판정 전 뉴스를 그대로 보여주면 "이 서비스가 선별한 뉴스"로 오해되기 때문입니다. 그래서 **수집 직후에는 화면이 변하지 않고, RA 처리가 끝난 시점에 검증된 뉴스가 한꺼번에 올라옵니다.** 미처리 배치가 쌓이고 있는지는 설정 > 로그(SET-006)에서 운영자가 확인합니다.
- **대시보드로 한눈에** — 기간별(전체/최근 30일/최근 7일) 뉴스 추이, 기업별·기술주제별 언급 순위, 주요 이슈(Insight), 기업 간 관계망(지식그래프)을 대시보드에서 확인합니다.

## 기술 스택

- **Backend**: Django 5.2 (서버 사이드 렌더링, 별도 API 레이어 없음)
- **Frontend**: HTMX(부분 업데이트) + Alpine.js(클라이언트 UI 상태) + Tailwind CSS
- **DB**: PostgreSQL 16 + pgvector (Docker)
- **외부 연동**: Naver News API, OpenDART API, Claude API(Anthropic), Voyage AI(임베딩), Slack Webhook
- **스케줄링**: APScheduler (in-process, `runserver`와 함께 기동 — 그래서 서버가 꺼져 있으면 그 시각 작업이 실행되지 않습니다. 로컬은 스케줄 비활성, 수동 수집)
- **시각화**: D3.js(지식그래프), 순수 SVG(대시보드 차트)

## 화면 구성

| 화면 ID | 내용 |
|---|---|
| `ALL-001` | 전체 대시보드 — 핵심 지표(일별 추이·기업/기술주제 랭킹), 주요 이슈, 최신 뉴스 |
| `NEWS-001~002` | 뉴스 목록·상세 |
| `REPORT-001~002` | 보고서 목록·상세 (마크다운 렌더링) |
| `SET-001~008` | 설정 — 데이터소스·키워드·프롬프트·스케줄·Slack·로그·기업·기술 주제 관리 |
| `GRAPH-001` | 지식그래프 — 금융사/보험사 × AI 기업 간 **실질 관계(RA가 라벨링한 기술협업·공급계약·투자 등)만** 엣지로 표시하는 관계망 |

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
  periods.py    # 대시보드·지식그래프 공통 기간 필터 유틸
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
| **research-analyst (RA)** | 수집된 뉴스로 실제 리서치 산출물(노이즈 정리·태깅 교정·시사점·지식그래프 관계 라벨링·주간 보고서) 생성. PM/PD/PE가 "플랫폼을 만드는" 축이라면 RA는 "플랫폼을 쓰는" 축 | 제한 없음(단 `.py` 구현은 소프트 제약) |

작업 유형별 호출 순서(신규 화면: PM→PD→PE, 버그 수정: PE만 등)를 포함한 전체 규칙은 [`CLAUDE.md`](./CLAUDE.md#서브에이전트-pmpdpera)를 참고하세요.

## 더 알아보기

- [`CLAUDE.md`](./CLAUDE.md) — 아키텍처 규칙, 화면 ID 체계, 서브에이전트(PM/PD/PE/RA) 워크플로우
- [`docs/planning.md`](./docs/planning.md) — 제품 비전과 정책(관련성 판단 기준, Insight 승격 기준 등)
- [`docs/design.md`](./docs/design.md) — 화면별 와이어프레임과 컴포넌트 스펙
- [`docs/dev.md`](./docs/dev.md) — 데이터 모델, URL 구조 등 기술 구현 현황
