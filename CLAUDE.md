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
- **뉴스룸은 이 게이트 밖이다** — `NewsroomArticle`은 `News`가 아니므로 `verified()`가 걸리지 않는다. 대신 `filter_status='passed'`가 게이트이고 **판정 주체가 RA가 아니라 LLM**이다. ⚠️ 두 규칙을 섞지 말 것 — 뉴스룸 조회 코드에 `verified()`를 찾다가 없다고 게이트가 없는 줄 알면 안 되고, 반대로 `News` 조회에 `filter_status`를 쓰려 해서도 안 된다. 🔴 **키워드와 저장 테이블도 완전히 분리한다** — `collect_naver()`가 활성 수집 키워드 전량을 순회하므로 뉴스룸 키워드를 `Keyword`에 넣으면 본 파이프라인이 그대로 오염된다. 상세는 `docs/planning.md` "뉴스룸" 절.
- **수집 실행 — 스케줄이 아니라 화면 버튼이다** (2026-09-04 확정). 수집과 RA 1~4번은 전부 **사람이 SET-010 "실행"에서 버튼을 눌러야만** 돈다. 🔴 **종전의 "프로덕션 배포 시 SET-004에서 스케줄을 재활성화한다"는 계획은 폐기됐다** — 프로덕션에서도 스케줄러를 켜지 않으므로 APScheduler와 EventBridge 모두 불필요하고, SET-004는 읽되 실행하지 않는 화면으로 남는다(처분은 별도 판단). 폐기 근거는 이 구조가 만들던 실패다: APScheduler가 `runserver` 프로세스 안에 있어서 서버가 09:00에 떠 있지 않으면 그날 실행이 **예약조차 되지 않았고**(등록 시점 기준으로 다음 실행을 계산하므로 misfire가 아니고, 따라서 유예 시간도 무의미), 이것이 2026-07-30~08-05 5회 연속 미실행의 원인이었다. **버튼 방식은 이 실패 모드를 구조적으로 없앤다.** ⚠️ **LLM 결과는 바로 반영되지 않는다** — 버튼 → LLM 판정 → 제안 목록 → 사람이 "확정"을 한 번 더 눌러야 DB에 반영된다(승인 게이트). 상세는 `docs/planning.md` "실행 방식 전환: 스케줄 자동에서 화면 버튼 + 승인 게이트로" 절.
- **pgvector** — `Embedding` 모델·코사인 유사도 인프라는 구축돼 있으나(임계값 0.82), 현재 관련 기사 판별은 research-analyst가 배치를 직접 읽어서 수행하며 pgvector는 사용하지 않는다. 수집량 증가로 병목이 되면 PE가 상시 자동 클러스터링으로 재구현하는 걸 검토한다.
- **프로덕션이 실제로 서 있다** (2026-09-11 구축). 🔴 **로컬이 dev이고 EC2가 prd이며, 두 환경은 완전히 같게 유지한다**(사용자 확정). 그래서 EC2도 로컬과 똑같이 **Docker로 PostgreSQL만 띄우고 앱은 호스트 venv에서 돌린다** — 앱을 컨테이너에 넣는 종전 설계는 폐기됐고 `Dockerfile`과 `.dockerignore`도 삭제됐다.

  | | 로컬 (dev) | EC2 (prd) |
  |---|---|---|
  | 브랜치 | `develop` | 🔴 `main` 만 |
  | Python | 3.12.10 + `venv/` | 3.12.14 + `venv/` |
  | 패키지 | `requirements.txt` — 🔴 **전이 의존성까지 전부 `==` 고정** | 같음 |
  | DB | `docker compose up -d db` | 같음 |
  | 앱 | `runserver` | `gunicorn` (systemd 유닛 `aimarketwatch`) |
  | 설정 | `config.settings.local` | `config.settings.production` |
  | 로그 | 터미널 | `sudo journalctl -u aimarketwatch -f` |

  - **배포는 `scripts/deploy.sh`** — `git pull` → db 기동 → `pg_isready` 대기 → `pip install` → `makemigrations --check` → `migrate` → `collectstatic` → `systemctl restart`. 🔴 **`main`이 아니면 스크립트가 멈춘다.**
  - 🔴 **개발한 것을 EC2에 올리려면 `develop`을 `main`으로 병합해야 한다.** 이 한 걸음을 빠뜨리면 EC2가 `pull`해도 아무것도 안 바뀐다.
  - 🔴 **패키지를 새로 깔거나 올렸으면 로컬에서 `pip freeze > requirements.txt`를 다시 돌린다.** 안 하면 EC2가 옛 버전에 묶인다. 실제로 한 번 갈렸다(anthropic 0.116.0 대 1.5.0).
  - ⚠️ **로컬 DB를 프로덕션으로 올리지 않는다.** 2026-09-11의 최초 이관은 프로덕션 DB가 비어 있을 때 정본을 처음 세운 것이고, **두 번째 이관은 예외가 아니라 위반이다.** 상세는 `docs/planning.md` 8-(b).
  - 🔴 **그래서 EC2는 지금 2026-09-11 덤프 상태로 동결돼 있다** (2026-09-11 확정, `docs/planning.md` 8-(b-1)). AI 가공 기능이 코드로 존재하지 않아(`services/llm.py`가 빈 파일이고 `anthropic` import가 저장소 전체에 0건) **EC2는 스스로 데이터를 가공하지 못하고 로컬만 자란다.** LLM 연동이 완료되는 시점(cutover)에 그때의 로컬 DB로 EC2를 한 번 통째 갈아엎고, **그 뒤로 로컬에서 EC2로 가는 방향은 영구히 닫힌다.** cutover가 마지막 이관이고 세 번째는 없다.
    - 🔴 **동결 기간에 EC2에서 수집 버튼, 설정 변경, Slack 발송을 하지 않는다.** 조회는 아무리 해도 무방하다. 셋 중 하나라도 하면 그 순간 EC2에 로컬과 다른 갈래가 생기고, **cutover의 갈아엎기가 그 갈래를 실제로 날린다.** 특히 `Report.slack_sent_at`이 지워지면 같은 보고서가 다시 나간다 — 보낸 메시지는 DB 밖에 있어 되돌릴 수 없다.
    - ⚠️ **cutover가 위반이 아닌 이유는 전적으로 이 동결 조건에 매달려 있다.** 동결이 지켜지면 EC2에 갈래가 애초에 생기지 않아 덮어쓰기가 「정본을 잃는 것」이 아니라 「정본의 자리를 옮기는 것」이 된다. **예외인 것은 cutover라는 사건이 아니라 동결이 지켜진 상태다.**
    - ⚠️ **cutover 이후에도 「자동」이 아니다.** 수집과 1번부터 4번까지는 여전히 사람이 SET-010에서 버튼을 눌러야 돈다. 바뀌는 것은 **어느 DB에 대고 실행하는가** 하나뿐이다.
  - ⚠️ **매일 평일 08:00 자동 시작, 19:00 자동 정지된다.** 그 시간 밖에 접속이 안 되는 것은 고장이 아니다. systemd 유닛이 `enabled`라 켜지면 앱도 같이 뜬다.

## 템플릿 주석 — `{# #}`는 한 줄 전용 (반복 재발 중, 반드시 지킬 것)

Django의 `{# ... #}`는 **한 줄만** 주석 처리한다. 여러 줄에 걸쳐 쓰면 첫 줄만 사라지고 **나머지가 사용자 화면에 그대로 출력된다.** 여러 줄 설명은 예외 없이 `{% comment %} ... {% endcomment %}`를 쓴다.

```django
{# 한 줄이면 이건 괜찮다 #}

{% comment %}
  두 줄 이상은 반드시 이 형태.
  {# #}로 쓰면 이 줄이 화면에 찍힌다.
{% endcomment %}
```

**왜 매번 강조하는가**: Django는 에러를 내지 않고 조용히 렌더한다. `manage.py check`도, 코드를 다시 읽는 것도 이걸 못 잡는다. 실제로 커밋 d61c35f에서 한 번, 2026-08-04 하루에만 세 번(`reports/detail.html`·`setting/logs.html`·`reports/list.html`) 재발했고 **전부 사용자가 화면에서 먼저 발견했다.**

**따라서 템플릿을 수정했으면 렌더 결과에 `{#`가 남았는지 확인한다.** 검증 스크립트에 `assert "{#" not in html` 한 줄을 항상 넣는다 — 눈으로 코드를 보는 것으로는 못 잡는다.

## 프로젝트 구조

```
apps/
  dashboard/   # 전체 대시보드 (ALL-001)
  news/        # 뉴스 목록·상세 (NEWS-001, NEWS-002)
  reports/     # 보고서 목록·상세 (REPORT-001, REPORT-002)
  setting/     # 데이터소스·키워드·프롬프트·스케줄·Slack·로그·기업·기술 주제 (SET-001~008)
  graph/       # 지식그래프 (GRAPH-001)
  newsroom/    # 뉴스룸 목록·카드 상세·기사 상세 (ROOM-001~003). 관리 화면은 setting 앱의 SET-009
services/
  collector.py  # 뉴스 수집 파이프라인
  llm.py        # Claude API 연동
  embedder.py   # 임베딩 생성 + 유사 기사 그룹핑
  periods.py    # 대시보드, 지식그래프 공통 기간 필터 유틸
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
`ALL-001` 대시보드 / `NEWS-001~002` 뉴스 / `REPORT-001~002` 보고서 / `SET-001~010` 설정 (`SET-007` 기업 관리, `SET-008` 기술 주제 관리, `SET-009` 뉴스룸 관리, `SET-010` 실행) / `GRAPH-001` 지식그래프 / `ROOM-001~003` 뉴스룸 (`ROOM-003` 기사 상세)

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
