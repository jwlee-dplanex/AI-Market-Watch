# AI Market Watch 개발 문서

## 1. 기술 스택

| 항목 | 기술 | 버전 |
|------|------|------|
| Language | Python | 3.12 |
| Framework | Django | 5.2 LTS |
| Database | PostgreSQL | 16 |
| DB 어댑터 | psycopg2 | 2.9.9 |
| ORM | Django ORM | — |
| 템플릿 | Django Templates | — |
| 스타일링 | Tailwind CSS | 3.4 |
| 부분 업데이트 | HTMX | 2.0 |
| UI 상태 관리 | Alpine.js | 3.14 |
| 벡터 검색 | pgvector | 0.3.6 |
| 임베딩 모델 | Voyage AI voyage-multilingual-2 (1024차원) | — |

### 통신 방식

- HTMX 요청 → Django view → HTML fragment 반환 (JSON 최소화)
- fetch() / DRF 별도 API 레이어 없음
- JSON 응답은 Alpine.js 연동이 필요한 예외 케이스에만 사용

### 패키지 목록 (requirements.txt)

```
Django==5.2
shortuuid
django-environ
psycopg2-binary
pgvector
anthropic
voyageai
langchain
langchain-anthropic
APScheduler
trafilatura
requests
beautifulsoup4
```

---

## 2. 외부 API

| API | 용도 | 인증 |
|-----|------|------|
| Naver News API | 뉴스 수집 | X-Naver-Client-Id / X-Naver-Client-Secret |
| OpenDART API | 공시 자료 수집 | API Key |
| 금융위원회 RSS | 공식 보도자료 수집 | 없음 (공개) |
| Claude Haiku (`claude-haiku-4-5-20251001`) | 뉴스 요약·관련성 판단 | Anthropic API Key |
| Claude Sonnet (`claude-sonnet-5`) | 인사이트·보고서 생성 (계획, 미구현) | Anthropic API Key |

---

## 3. 데이터 모델

### 핵심 테이블

**News** — 수집된 뉴스 원문

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| title | CharField(500) | 제목 |
| url | URLField | 원문 URL |
| url_hash | CharField(64) | URL SHA-256 해시 (중복 제거) |
| body | TextField | 본문 |
| image_url | URLField(null) | 썸네일 URL (없으면 null) |
| source_type | CharField | 자유 텍스트 (choices 제약 없음, 현재는 `naver_news`만 사용) |
| summary | TextField(null) | LLM 생성 요약 |
| is_processed | BooleanField | LLM 처리(관련성 판단·요약) 완료 여부 |
| is_relevant | BooleanField | LLM이 판단한 관련성 (기본값 True, 처리 후 false면 목록·대시보드에서 숨김) |
| published_at | DateTimeField | 발행일 |
| collected_at | DateTimeField | 수집일 |

---

**ExcludedURL** — 삭제된 뉴스의 URL 해시 (재수집 방지)

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| url_hash | CharField(64, unique) | 삭제된 뉴스의 URL 해시 |
| deleted_at | DateTimeField | 삭제 시각 |

뉴스 삭제(`news_delete`) 시 `url_hash`를 여기에 기록. `collect_naver()`가 수집 시 이 테이블도 확인해서 한 번 삭제한 URL은 다시 저장하지 않음. 제목·URL 원문은 저장하지 않으므로 "언제 몇 건 삭제했는지"만 알 수 있고 무엇을 삭제했는지는 복원 불가.

---

**Embedding** — 뉴스 벡터

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| news | OneToOneField(News) | |
| vector | VectorField(1024) | pgvector 1024차원 벡터 |
| model | CharField | 사용 임베딩 모델명 |
| created_at | DateTimeField | |

---

**IssueGroup** — 유사 뉴스 묶음

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| title | CharField(null) | 이슈 제목 |
| summary | TextField(null) | 이슈 요약 |
| created_at | DateTimeField | |

---

**IssueGroupNews** — IssueGroup ↔ News M:N

| 필드 | 타입 |
|------|------|
| issue_group | ForeignKey(IssueGroup) |
| news | ForeignKey(News) |

---

**Insight** — LLM 생성 인사이트

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| issue_group | ForeignKey(IssueGroup) | |
| content | TextField | 주요 흐름 분석 |
| dplanex_implication | TextField | DPLANEX 시사점 |
| created_at | DateTimeField | |

---

**Report** — 주간 AI 인사이트 보고서

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| year | IntegerField | 연도 |
| week | IntegerField | 주차 |
| date_from | DateField | 해당 주 시작일 |
| date_to | DateField | 해당 주 종료일 |
| title | CharField | 보고서 제목 |
| overview | TextField | 주요 동향 개요 |
| content | TextField | 주요 이슈 + 시사점 |
| status | CharField | 생성중·완료·실패 |
| slack_sent_at | DateTimeField(null) | Slack 발송 시각 |
| created_at | DateTimeField | |

---

**ReportNews** — Report ↔ News M:N

| 필드 | 타입 |
|------|------|
| report | ForeignKey(Report) |
| news | ForeignKey(News) |

---

### 운영·설정 테이블

**DataSource** — 수집 대상

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| name | CharField | 소스명 |
| url | URLField | 수집 URL |
| source_type | CharField | `api` / `rss` / `crawl` |
| schedule | CharField | 실행 주기 설명 |
| is_active | BooleanField | 활성 여부 |

---

**Keyword** — 수집·제외 키워드

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| keyword | CharField | 키워드 |
| keyword_type | CharField | `수집` / `제외` |
| sort | CharField | `date`(최신순) / `sim`(관련도순) — 수집 키워드 전용 |
| is_active | BooleanField | 활성 여부 |

---

**Prompt** — Claude 프롬프트

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| name | CharField | 프롬프트명 |
| purpose | CharField | 목적 |
| content | TextField | 프롬프트 내용 |
| updated_at | DateTimeField | |

---

**Schedule** — 실행 스케줄

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| schedule_type | CharField | `collect` / `report` |
| cron_expr | CharField | cron 표현식 |
| is_active | BooleanField | 활성 여부 |
| last_run_at | DateTimeField(null) | 마지막 실행 시각 |
| next_run_at | DateTimeField(null) | 다음 실행 시각 |

---

**CollectionLog** — 수집 실행 이력

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| source | ForeignKey(DataSource) | |
| started_at | DateTimeField | 실행 시작 시각 |
| collected_count | IntegerField | 수집 건수 |
| status | CharField | `success` / `fail` |
| error_message | TextField(null) | 오류 메시지 |

---

**LLMLog** — Claude API 호출 이력

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| news | ForeignKey(News, null) | |
| prompt_name | CharField | 사용 프롬프트명 |
| status | CharField | `success` / `fail` |
| input_tokens | IntegerField | 입력 토큰 수 |
| output_tokens | IntegerField | 출력 토큰 수 |
| error_message | TextField(null) | 오류 메시지 |
| created_at | DateTimeField | |

---

**SlackConfig** — Slack 전송 설정

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| channel_name | CharField | 채널명 |
| webhook_url | URLField | Webhook URL |
| is_active | BooleanField | 활성 여부 |
| last_sent_at | DateTimeField(null) | 마지막 발송 시각 |

---

## 4. 프로젝트 구조

```
ai_market_watch/
├── config/
│   ├── settings/
│   │   ├── base.py          # 공통 설정
│   │   ├── local.py         # 개발 환경
│   │   └── production.py    # 운영 환경
│   ├── urls.py
│   └── wsgi.py
│
├── apps/
│   ├── dashboard/           # 전체 대시보드 (ALL-001)
│   │   ├── views.py
│   │   └── urls.py
│   ├── news/                # 뉴스 (NEWS-001, NEWS-002)
│   │   ├── models.py        # News, Embedding, IssueGroup, Insight
│   │   ├── views.py
│   │   └── urls.py
│   ├── reports/             # 보고서 (REPORT-001, REPORT-002)
│   │   ├── models.py        # Report, ReportNews
│   │   ├── views.py
│   │   └── urls.py
│   └── setting/             # 설정 (SET-001 ~ SET-006)
│       ├── models.py        # DataSource, Keyword, Prompt, Schedule, SlackConfig, CollectionLog, LLMLog
│       ├── views.py
│       └── urls.py
│
├── services/
│   ├── collector.py         # 수집 파이프라인
│   ├── llm.py               # Claude API 연동
│   ├── embedder.py          # 임베딩 생성
│   └── scheduler.py         # 스케줄 실행
│
├── templates/
│   ├── base.html            # 공통 레이아웃 (헤더·사이드바·푸터)
│   ├── dashboard/
│   ├── news/
│   │   ├── list.html
│   │   ├── detail.html
│   │   └── _list.html       # HTMX 파션
│   ├── reports/
│   └── setting/
│
├── static/
│   ├── css/
│   └── js/
│
├── .env
├── .env.example
├── manage.py
└── requirements.txt
```

### URL 구조

| URL | 화면 |
|-----|------|
| `/` | 전체 대시보드 (ALL-001) |
| `/news/` | 뉴스 목록 (NEWS-001) |
| `/news/<uid>/` | 뉴스 상세 (NEWS-002) |
| `/news/<uid>/delete/` | 뉴스 삭제 (POST) |
| `/reports/` | 보고서 목록 (REPORT-001) |
| `/reports/<id>/` | 보고서 상세 (REPORT-002) |
| `/setting/sources/` | 데이터 소스 (SET-001) |
| `/setting/sources/<pk>/toggle/` | 데이터 소스 활성 토글 (POST) |
| `/setting/sources/collect-now/` | 수동 수집 실행 (POST) |
| `/setting/sources/process-llm-now/` | AI 관련성 판단·요약 수동 실행 (POST) |
| `/setting/keywords/` | 키워드 (SET-002) |
| `/setting/keywords/add/` | 키워드 추가 (POST) |
| `/setting/keywords/<pk>/update/` | 키워드 수정 (POST) |
| `/setting/keywords/<pk>/delete/` | 키워드 삭제 (POST) |
| `/setting/prompts/` | 프롬프트 (SET-003) |
| `/setting/schedule/` | 스케줄 (SET-004) |
| `/setting/slack/` | Slack (SET-005) |
| `/setting/logs/` | 처리 이력 (SET-006) |
| `/setting/organizations/` | 기관 관리 |
| `/setting/organizations/save/` | 기관 추가·수정 (POST) |
| `/setting/organizations/<pk>/toggle/` | 기관 활성 토글 (POST) |
| `/setting/organizations/<pk>/delete/` | 기관 삭제 (POST) |
| `/setting/remap/` | 기관 재매핑 (POST) |

---

## 5. 수집 파이프라인

### 흐름

```
[DataSource: Naver News API (is_active 체크)]
    ↓ 활성인 경우에만
[수집 키워드 리스트] → 키워드별 Naver API 호출 (kw.sort 적용)
    ↓
수집 → 제외 키워드 필터 → 중복 제거(url_hash) → 삭제 이력 체크(ExcludedURL) → News 저장 → _link_organizations() → LLM 처리 대기
```

### 소스별 수집 방식

| 소스 | 방식 | 주요 수집 필드 |
|------|------|----------------|
| Naver News API | `GET openapi.naver.com/v1/search/news.json?query=키워드&sort=date|sim` | title, link, description, pubDate |

> OpenDART API, 금융위원회 RSS는 계획에 포함되어 있으나 미구현 상태입니다.

### 정규화

소스별로 다른 필드명을 News 모델 형태로 통일합니다.

```python
{
    "title": ...,
    "url": ...,
    "body": ...,
    "image_url": ...,   # 없으면 None
    "published_at": ...,
    "source_type": "naver_news" | "opendart" | "rss"
}
```

### 중복 제거

URL을 SHA-256 해싱해서 `url_hash`로 비교합니다.

```python
url_hash = hashlib.sha256(url.encode()).hexdigest()
if News.objects.filter(url_hash=url_hash).exists():
    skip()
```

### 이미지 처리

- `image_url` 필드에 URL만 저장, 직접 다운로드 없음
- Naver News API 응답의 `thumbnail` 필드 사용
- OpenDART, RSS는 이미지 없으므로 null

### 실행 로그

파이프라인 실행 시작·종료 시 CollectionLog 자동 기록합니다.

---

## 6. LLM 연동

### 용도별 모델

| 용도 | 모델 | 처리 단위 |
|------|------|-----------|
| 뉴스 요약·관련성 판단 | claude-haiku-4-5-20251001 | 뉴스 1건 → 1회 호출 |
| 인사이트 생성 (계획, 미구현) | claude-sonnet-5 | 이슈 그룹 단위 |
| 주간 보고서 생성 (계획, 미구현) | claude-sonnet-5 | 주차 단위 |

### 뉴스 단건 처리 — 관련성 판단 + 요약 (구현 완료)

**트리거**: 설정 > 데이터 소스 페이지의 "AI 처리" 버튼 (수동). 자동 스케줄은 아직 없음.

`services/llm.py`의 `process_unclassified()`가 `is_processed=False`인 뉴스를 순회하며 `classify_news()`를 1건씩 호출합니다.

- 프롬프트는 하드코딩이 아니라 `Prompt` 모델(`name="뉴스 요약"`)에서 로드 → 설정 > 프롬프트 화면에서 코드 수정 없이 문구 조정 가능 (마이그레이션으로 기본값 시딩됨)
- 본문은 토큰 비용 절약을 위해 앞 6,000자까지만 프롬프트에 포함
- 응답이 ` ```json ` 코드펜스로 감싸져 오는 경우를 대비해 파싱 전에 방어적으로 제거

프롬프트 응답 형식:
```json
{
  "is_relevant": true,
  "summary": "2-3문장 요약 (is_relevant가 false면 빈 문자열)"
}
```

처리 결과는 `News.is_relevant`, `News.summary`, `News.is_processed=True`에 저장됩니다. **`is_relevant=False`인 뉴스는 삭제되지 않고, 뉴스 목록·대시보드 조회 쿼리에서만 `filter(is_relevant=True)`로 제외**됩니다 (상세 페이지 URL 직접 접근은 가능).

### 인사이트 생성 (계획, 미구현)

이슈 그룹 내 뉴스 요약을 묶어 Claude Sonnet에게 전달합니다.

프롬프트 응답 형식:
```json
{
  "content": "주요 흐름 분석",
  "dplanex_implication": "DPLANEX 시사점"
}
```

### 주간 보고서 생성 (계획, 미구현)

해당 주차 인사이트를 모아 보고서를 자동 생성합니다.

프롬프트 응답 형식:
```json
{
  "title": "보고서 제목",
  "overview": "주요 동향 개요",
  "content": "주요 이슈 + 시사점"
}
```

### 에러 처리

| 상황 | 처리 방식 |
|------|-----------|
| JSON 파싱 실패 / API 호출 예외 | `is_processed=False` 유지(재시도 대상으로 남음), `LLMLog`에 fail 기록, `stats["errors"]` 카운트 |
| 처리 실패한 뉴스 | 자동 재시도 없음 — "AI 처리" 버튼을 다시 눌러 다음 배치 실행 시 재시도됨 |

모든 호출은 LLMLog에 프롬프트명·토큰 수·성공/실패 여부를 기록합니다 (설정 > 로그 화면에서 확인 가능).

---

## 7. 임베딩 & 유사 기사

### 임베딩 생성

`title + body`를 합쳐 Voyage AI API로 임베딩합니다.

```python
# services/embedder.py
text = f"{news.title}\n{news.body}"
result = client.embed([text], model=settings.EMBEDDING_MODEL)
```

모델: `voyage-multilingual-2` (1024차원, Voyage AI API, 계정당 5천만 토큰 무료)

### 유사 기사 그룹핑

```
임베딩 생성
    → 기존 뉴스와 코사인 유사도 비교
    → 유사도 ≥ 0.82 : 기존 IssueGroup에 추가
    → 유사도  < 0.82 : 새 IssueGroup 생성
```

임계값 0.82는 실제 데이터 기준으로 조정 가능합니다.

### pgvector 설정

```python
# apps/news/models.py
from pgvector.django import VectorField

class Embedding(models.Model):
    news   = models.OneToOneField(News, on_delete=models.CASCADE)
    vector = VectorField(dimensions=1024)
```

---

## 8. 스케줄러

APScheduler를 사용합니다. Django 앱 시작 시 `apps.py`에서 자동 실행됩니다.

**현재 실제로 자동화된 작업은 "뉴스 수집" 하나뿐입니다.** `services/scheduler.py`의 `_job_collect()`가 `collect_naver()`를 호출해 `CollectionLog`를 남기는 것까지만 구현돼 있고, `Schedule.schedule_type`에 `"report"` 타입이 모델상 정의는 돼 있지만 실제로 등록·실행되는 잡은 없습니다.

### 실행 스케줄

| 작업 | 상태 | 주기(설정 시) |
|------|------|------|
| 뉴스 수집 | **구현 완료·자동 실행** | Schedule 모델(SET-004)에 등록한 cron 표현식대로 |
| AI 관련성 판단·요약 | 수동 버튼만 구현 (설정 > 데이터 소스 "AI 처리") | 자동 스케줄 없음 |
| 임베딩 생성 | 코드는 있으나(`services/embedder.py`) 트리거(버튼·스케줄) 없음 | — |
| 이슈 그룹핑 | 미구현 | — |
| 주간 보고서 생성 | 미구현 | — |
| Slack 발송 | 미구현 | — |

### Schedule 모델 연동

`Schedule` 모델의 `is_active` 값을 읽어 실행 여부를 제어합니다. SET-004 화면에서 켜고 끌 수 있습니다. (현재는 `schedule_type="collect"`만 실제로 동작)

---

## 9. 환경 설정

### .env 구조

```bash
# Django
DJANGO_SECRET_KEY=
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DB_NAME=ai_market_watch
DB_USER=
DB_PASSWORD=
DB_HOST=localhost
DB_PORT=5432

# Naver News API
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=

# OpenDART API
OPENDART_API_KEY=

# Claude API
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL_FAST=claude-haiku-4-5-20251001
ANTHROPIC_MODEL_SMART=claude-sonnet-5

# Slack
SLACK_WEBHOOK_URL=

# Voyage AI (임베딩)
VOYAGE_API_KEY=
EMBEDDING_MODEL=voyage-multilingual-2
EMBEDDING_SIMILARITY_THRESHOLD=0.82
```

`.env.example`은 키 이름만 남기고 값은 비워서 커밋합니다.

### Django settings 분리

```
config/settings/
├── base.py       # 공통 설정 (django-environ으로 .env 로딩)
├── local.py      # DEBUG=True
└── production.py # DEBUG=False
```

실행:
```bash
python manage.py runserver --settings=config.settings.local
```

### .gitignore 필수 항목

```
.env
*.pyc
__pycache__/
/static/
/media/
```

---

## 10. 배포

로컬 단일 실행 (1단계)

```bash
python manage.py runserver --settings=config.settings.local
```

스케줄러는 `runserver` 실행 시 자동으로 함께 시작됩니다.
