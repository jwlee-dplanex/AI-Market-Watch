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
| 임베딩 모델 | paraphrase-multilingual-MiniLM-L12-v2 | — |

### 통신 방식

- HTMX 요청 → Django view → HTML fragment 반환 (JSON 최소화)
- fetch() / DRF 별도 API 레이어 없음
- JSON 응답은 Alpine.js 연동이 필요한 예외 케이스에만 사용

### 패키지 목록 (requirements.txt)

```
django==5.2
psycopg2==2.9.9
pgvector==0.3.6
django-pgvector==0.3.0
django-environ==0.11.2
anthropic==0.40.0
sentence-transformers==3.3.1
apscheduler==3.10.4
gunicorn==23.0.0
```

---

## 2. 외부 API

| API | 용도 | 인증 |
|-----|------|------|
| Naver News API | 뉴스 수집 | X-Naver-Client-Id / X-Naver-Client-Secret |
| OpenDART API | 공시 자료 수집 | API Key |
| 금융위원회 RSS | 공식 보도자료 수집 | 없음 (공개) |
| Claude Haiku (`claude-haiku-4-5-20251001`) | 뉴스 요약·분류·태깅 | Anthropic API Key |
| Claude Sonnet (`claude-sonnet-4-6`) | 인사이트·보고서 생성 | Anthropic API Key |

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
| source_type | CharField | `naver_news` / `opendart` / `rss` |
| category | CharField | 기술흐름·기업사례·금융권활용·규제·정책·경쟁사동향 |
| tags | JSONField | 키-값 구조 태그 |
| summary | TextField(null) | LLM 생성 요약 |
| is_processed | BooleanField | LLM 처리 완료 여부 |
| published_at | DateTimeField | 발행일 |
| collected_at | DateTimeField | 수집일 |

tags 구조:
```json
{
  "산업": ["금융", "보험"],
  "기업": ["KB국민은행"],
  "기술": ["AI Agent", "LLM"]
}
```

---

**Embedding** — 뉴스 벡터

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| news | OneToOneField(News) | |
| vector | VectorField(384) | pgvector 384차원 벡터 |
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
│   └── administration/      # 설정 (SET-001 ~ SET-006)
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
│   └── administration/
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
| `/news/<id>/` | 뉴스 상세 (NEWS-002) |
| `/reports/` | 보고서 목록 (REPORT-001) |
| `/reports/<id>/` | 보고서 상세 (REPORT-002) |
| `/administration/sources/` | 데이터 소스 (SET-001) |
| `/administration/keywords/` | 키워드 (SET-002) |
| `/administration/prompts/` | 프롬프트 (SET-003) |
| `/administration/schedule/` | 스케줄 (SET-004) |
| `/administration/slack/` | Slack (SET-005) |
| `/administration/logs/` | 처리 이력 (SET-006) |

---

## 5. 수집 파이프라인

### 흐름

```
[Naver News API]     ┐
[OpenDART API]       ├──→ 수집 → 정규화 → 중복 제거 → News 저장 → LLM 처리 대기
[금융위원회 RSS]     ┘
```

### 소스별 수집 방식

| 소스 | 방식 | 주요 수집 필드 |
|------|------|----------------|
| Naver News API | `GET openapi.naver.com/v1/search/news.json?query=키워드` | title, link, description, pubDate, thumbnail |
| OpenDART API | `GET opendart.fss.or.kr/api/list.json` | corp_name, report_nm, rcept_dt, rcept_no |
| 금융위원회 RSS | XML 파싱 | title, link, pubDate |

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
| 뉴스 요약·분류·태깅 | claude-haiku-4-5-20251001 | 뉴스 1건 → 1회 호출 |
| 인사이트 생성 | claude-sonnet-4-6 | 이슈 그룹 단위 |
| 주간 보고서 생성 | claude-sonnet-4-6 | 주차 단위 |

### 뉴스 단건 처리

1회 호출로 요약·카테고리·태그를 JSON으로 받습니다.

프롬프트 응답 형식:
```json
{
  "summary": "2-3문장 요약",
  "category": "기술흐름 | 기업사례 | 금융권활용 | 규제·정책 | 경쟁사동향",
  "tags": {
    "산업": [],
    "기업": [],
    "기술": []
  }
}
```

처리 완료 후 `is_processed = True`로 업데이트합니다.

### 인사이트 생성

이슈 그룹 내 뉴스 요약을 묶어 Claude Sonnet에게 전달합니다.

인사이트 프롬프트에 DPLANEX 사업 맥락을 포함합니다.

```
DPLANEX 사업 맥락:
- KANDLE: 금융권 AI 플랫폼
- AI Studio: AI 개발·운영 환경
- 관계사 AX 지원: 관계사 AI 전환 지원 사업
```

프롬프트 응답 형식:
```json
{
  "content": "주요 흐름 분석",
  "dplanex_implication": "DPLANEX 시사점"
}
```

### 주간 보고서 생성

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
| JSON 파싱 실패 | `is_processed=False` 유지, LLMLog에 error 기록 |
| API 타임아웃 | 최대 3회 재시도 후 fail 기록 |
| 처리 실패 | 다음 스케줄 실행 시 재처리 |

모든 호출은 LLMLog에 토큰 수, 성공/실패 여부를 기록합니다.

---

## 7. 임베딩 & 유사 기사

### 임베딩 생성

`title + summary + tags`를 합쳐 임베딩합니다.

```python
tags_flat = " ".join([v for values in news.tags.values() for v in values])
text_to_embed = f"{news.title} {news.summary} {tags_flat}"
vector = model.encode(text_to_embed).tolist()
```

모델: `paraphrase-multilingual-MiniLM-L12-v2` (384차원, 로컬 실행, 무료)

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
    vector = VectorField(dimensions=384)
```

---

## 8. 스케줄러

APScheduler를 사용합니다. Django 앱 시작 시 `apps.py`에서 자동 실행됩니다.

### 실행 스케줄

| 작업 | 주기 | 시간 |
|------|------|------|
| 뉴스 수집 | 매일 | 09:00 |
| LLM 처리 (요약·분류·태깅) | 매일 | 09:30 |
| 임베딩 & 이슈 그룹핑 | 매일 | 10:00 |
| 주간 보고서 생성 | 매주 월요일 | 10:30 |
| Slack 발송 | 매주 월요일 | 11:00 |

### Schedule 모델 연동

Schedule 모델의 `is_active` 값을 읽어 실행 여부를 제어합니다. SET-004 화면에서 켜고 끌 수 있습니다.

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
ANTHROPIC_MODEL_SMART=claude-sonnet-4-6

# Slack
SLACK_WEBHOOK_URL=

# Embedding
EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2
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
