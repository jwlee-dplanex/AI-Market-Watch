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
Markdown
bleach
```

---

## 2. 외부 API

| API | 용도 | 인증 |
|-----|------|------|
| Naver News API | 뉴스 수집 | X-Naver-Client-Id / X-Naver-Client-Secret |
| OpenDART API | 공시 자료 수집 | API Key |
| 금융위원회 RSS | 공식 보도자료 수집 | 없음 (공개) |
| Claude Haiku (`claude-haiku-4-5-20251001`) | (계획, 상시 자동화 파이프라인 구현 시 사용 예정. 현재는 research-analyst 에이전트가 온디맨드로 관련성 판정 수행) | Anthropic API Key |
| Claude Sonnet (`claude-sonnet-5`) | 인사이트·보고서 생성 — research-analyst 에이전트가 온디맨드 세션에서 직접 작성 | Anthropic API Key |

---

## 3. 데이터 모델

### 핵심 테이블

**News** — 수집된 뉴스 원문

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| uid | UUIDField | shortuuid 기반 공개 식별자 (URL에 노출, unique·db_index) |
| title | CharField(500) | 제목 |
| url | URLField | 원문 URL |
| url_hash | CharField(64) | URL SHA-256 해시 (중복 제거) |
| body | TextField | 본문 |
| image_url | URLField(null) | 썸네일 URL (없으면 null) |
| source_type | CharField | 자유 텍스트 (choices 제약 없음, 현재는 `naver_news`만 사용) |
| published_at | DateTimeField | 발행일 |
| collected_at | DateTimeField | 수집일 |
| organizations | ManyToManyField(Organization) | 수집 시 별칭 매칭으로 자동 연결되는 기업 (related_name="news") |
| tech_topics | ManyToManyField(TechTopic) | 수집 시 별칭 매칭으로 자동 연결되는 기술 주제 (related_name="news") |

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

**Insight** — research-analyst 에이전트가 온디맨드로 작성하는 인사이트. 별도 그룹 테이블 없이 `News`와 직접 M:N 연결됩니다.

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| title | CharField(500) | 이슈를 대표하는 제목 |
| news | ManyToManyField(News, through=InsightNews) | 근거로 삼은 News 전체 (출처 표기 역할 겸함) |
| content | TextField | 주요 흐름 분석 |
| implication | TextField | 시사점 (필드명이 `implication`이며 `dplanex_implication`이 아님) |
| created_at | DateTimeField | |

---

**InsightNews** — Insight ↔ News M:N

| 필드 | 타입 |
|------|------|
| insight | ForeignKey(Insight) |
| news | ForeignKey(News) |

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

**Organization** — 기업 마스터 (뉴스 자동 매핑용)

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| name | CharField(100, unique) | 기업명 |
| org_type | CharField(20) | `금융사` / `보험사` / `AI` |
| aliases | JSONField(default=list) | 별칭 목록 (수집 시 본문 매칭에 사용) |
| is_active | BooleanField | 활성 여부 |

---

**TechTopic** — 기술 주제 마스터 (Organization과 병존하는 두 번째 분류 축)

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| name | CharField(100, unique) | 기술 주제명 |
| aliases | JSONField(default=list) | 별칭 목록 |
| is_active | BooleanField | 활성 여부 |

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
│   │   ├── models.py        # News, ExcludedURL, Embedding, Insight, InsightNews
│   │   ├── views.py
│   │   └── urls.py
│   ├── reports/             # 보고서 (REPORT-001, REPORT-002)
│   │   ├── models.py        # Report, ReportNews
│   │   ├── views.py
│   │   └── urls.py
│   ├── setting/             # 설정 (SET-001 ~ SET-008)
│   │   ├── models.py        # DataSource, Keyword, Prompt, Schedule, SlackConfig, CollectionLog, LLMLog, Organization, TechTopic
│   │   ├── views.py
│   │   └── urls.py
│   └── graph/               # 지식그래프 (GRAPH-001)
│       ├── views.py         # graph(관계도), graph_org_panel(HTMX 패널)
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
│   ├── setting/
│   └── graph/
│       ├── index.html       # GRAPH-001 D3.js 관계도
│       └── _org_panel.html  # 기업 노드 클릭 시 HTMX 패널
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
| `/setting/keywords/` | 키워드 (SET-002) |
| `/setting/keywords/add/` | 키워드 추가 (POST) |
| `/setting/keywords/<pk>/update/` | 키워드 수정 (POST) |
| `/setting/keywords/<pk>/delete/` | 키워드 삭제 (POST) |
| `/setting/prompts/` | 프롬프트 (SET-003) |
| `/setting/schedule/` | 스케줄 (SET-004) |
| `/setting/schedule/save/` | 스케줄 추가·수정 (POST) |
| `/setting/schedule/<pk>/toggle/` | 스케줄 활성 토글 (POST) |
| `/setting/schedule/<pk>/delete/` | 스케줄 삭제 (POST) |
| `/setting/slack/` | Slack (SET-005) |
| `/setting/logs/` | 처리 이력 (SET-006) |
| `/setting/organizations/` | 기업 관리 (SET-007) |
| `/setting/organizations/save/` | 기업 추가·수정 (POST) |
| `/setting/organizations/<pk>/toggle/` | 기업 활성 토글 (POST) |
| `/setting/organizations/<pk>/delete/` | 기업 삭제 (POST) |
| `/setting/remap/` | 기업 재매핑 (POST) |
| `/setting/tech-topics/` | 기술 주제 관리 (SET-008) |
| `/setting/tech-topics/save/` | 기술 주제 추가·수정 (POST) |
| `/setting/tech-topics/<pk>/toggle/` | 기술 주제 활성 토글 (POST) |
| `/setting/tech-topics/<pk>/delete/` | 기술 주제 삭제 (POST) |
| `/setting/tech-topics/remap/` | 기술 주제 재매핑 (POST) |
| `/graph/` | 지식그래프 (GRAPH-001) |
| `/graph/orgs/<pk>/panel/` | 기업 노드 관련뉴스 패널 (HTMX 조각) |

---

## 대시보드 집계 (ALL-001)

전체 대시보드 "핵심 지표" 3개 카드는 모두 **최근 7일**(오늘 포함 7일) 범위를 기준으로 `apps/dashboard/views.py`에서 집계합니다.

- **일별 뉴스 건수 추이** (`_build_daily_counts`) — 최근 7일 각 날짜별 `News.published_at` 기준 수집 건수를 집계합니다. 데이터가 없는 날짜도 0건으로 채워 항상 7개 포인트를 반환합니다.
- **기업별 건수 Top 10** (`_build_org_ranking`) — 활성(`is_active=True`) `Organization` 중 최근 7일간 연결된 `News` 건수가 1건 이상인 기업을 건수 내림차순으로 최대 10개까지 집계합니다. 기업별로 최근 뉴스 최대 5건을 함께 담아 호버 팝오버에 사용합니다.
- **기술 주제별 언급 건수** (`_build_tech_topic_counts`) — 활성 `TechTopic` 중 최근 7일간 연결된 `News` 건수가 1건 이상인 주제를 건수 내림차순으로 집계합니다(0건 주제는 제외). 기업별 Top 10과 동일하게 최근 뉴스 최대 5건을 함께 담습니다.

세 지표 모두 `News.organizations`/`News.tech_topics` M2M(수집 시 `services/collector.py`의 별칭 매칭으로 자동 연결)을 근거로 집계하며, 별도의 캐시·배치 집계 테이블 없이 매 요청마다 실시간으로 계산합니다.

---

## 지식그래프 (GRAPH-001)

`apps/graph/views.py`가 활성 기업(`Organization`) 간 공동 등장 관계를 D3.js force-directed 그래프로 시각화합니다.

- **노드** — 활성(`is_active=True`) `Organization` 중 연결된 `News`가 1건 이상인 기업만 노드로 만듭니다. `symbolSize`는 `news_count`에 비례해 `max(14, min(40, 14 + news_count * 2))`로 14~40 범위로 계산합니다. `category`는 `org_type`(금융사/보험사/AI)을 인덱스(0/1/2)로 매핑해 색상 구분에 사용합니다.
- **엣지** — 같은 `News`에 2개 이상 기업이 함께 등장할 때, 등장한 기업 쌍마다 공동등장 가중치(`value`)를 누적합니다. **단 `ALLOWED_TYPE_PAIRS`(`{금융사, AI}`, `{보험사, AI}`) 조합만 엣지로 허용**하며, 금융사-금융사·보험사-보험사·AI-AI·금융사-보험사 조합은 제외합니다.
- **HTMX 패널** — 노드 클릭 시 `/graph/orgs/<pk>/panel/`(`graph_org_panel`)이 해당 기업에 연결된 최근 `News` 10건을 `graph/_org_panel.html` 조각으로 반환합니다.
- **렌더링** — `templates/graph/index.html`에서 D3.js v7.8.5(CDN)로 force simulation을 구성합니다.

---

## 5. 수집 파이프라인

### 흐름

```
[DataSource: Naver News API (is_active 체크)]
    ↓ 활성인 경우에만
[수집 키워드 리스트] → 키워드별 Naver API 호출 (kw.sort 적용)
    ↓
수집 → 제외 키워드 필터 → 중복 제거(url_hash) → 삭제 이력 체크(ExcludedURL) → News 저장 → _link_organizations() → _link_tech_topics() → research-analyst 에이전트의 온디맨드 처리 대기
```

기업·기술 주제 마스터(별칭)를 SET-007/SET-008 화면에서 수정한 뒤에는 각 화면의 재매핑 버튼(`remap_organizations()`/`remap_tech_topics()`)으로 이미 수집된 News 전체의 매핑을 다시 계산할 수 있습니다.

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

뉴스 수집 이후의 관련성 판정·삭제·관련 기사 묶기·인사이트 작성·보고서 편집은 전부 **research-analyst(RA) 에이전트가 사람이 Claude Code 세션을 열 때마다 온디맨드로 직접 수행**합니다. 예전에 있던 "AI 처리" 버튼(`services/llm.py`의 `classify_news()`/`process_unclassified()`, `News.is_relevant`/`is_processed`/`summary` 필드 기반 자동 분류)은 제거되었습니다 — 병행되는 자동 분류 파이프라인이 없습니다.

### 용도별 모델

| 용도 | 모델 | 처리 단위 |
|------|------|-----------|
| 관련성 판정·노이즈 삭제, 관련 기사 묶기, 인사이트 작성 (RA 온디맨드) | claude-sonnet-5 | RA 세션에서 배치 단위로 직접 판단 |
| 주간 보고서 편집 (RA 온디맨드) | claude-sonnet-5 | 주차 단위 |
| 상시 자동화 파이프라인 (계획, 미구현) | claude-haiku-4-5-20251001 (예정) | 수집량 증가로 병목이 될 시점에 PE가 재검토 |

### RA의 온디맨드 처리 흐름

1. **노이즈 판정 + 삭제** — 갓 수집된 뉴스 배치를 직접 읽고 PM이 정의한 관련성 기준으로 판단, `product-engineer`의 안전 삭제 패턴(`ExcludedURL.objects.get_or_create()` 선기록 후 `news.delete()`, 건별 개별 처리)을 그대로 따라 직접 삭제까지 실행합니다. 남은 `News`는 삭제되지 않았다는 사실 자체가 "관련 있음"을 의미하므로 별도 플래그(`is_relevant`)가 필요 없습니다.
2. **관련 기사 찾기 + Insight 작성** — 남은 배치의 제목·본문을 직접 읽고(pgvector 쿼리 미사용) 같은 사건을 다루는 기사를 식별해 Django ORM으로 `Insight`(`title`/`content`/`implication`)를 작성하고 `insight.news.set([...])`로 근거 `News`를 연결합니다. 별도 그룹 테이블(과거 `IssueGroup`) 없이 `Insight` 자체가 "이 기사들 + 이 분석"의 단위입니다.
3. **주간 보고서 편집** — `Report.title`/`overview`/`content`를 편집하고 `ReportNews`로 근거 `News`를 직접 연결합니다.

모든 인사이트·보고서 문단은 실제로 연결된 `News`를 출처로 추적 가능해야 하며, 근거 없는 내용은 작성하지 않는 것이 원칙입니다 (RA 에이전트 정책).

### 보고서 마크다운 렌더링

RA가 `Report.overview`/`Report.content`에 작성하는 마크다운은 `apps/reports/templatetags/report_extras.py`의 `markdown` 커스텀 템플릿 필터로 HTML로 변환됩니다. `templates/reports/detail.html`에서 `{{ report.overview|markdown }}`/`{{ report.content|markdown }}`로 사용합니다.

- **python-markdown**(`Markdown` 패키지)으로 마크다운을 HTML로 변환(`sane_lists` 확장 사용).
- **bleach**로 변환된 HTML을 화이트리스트 방식으로 정제(`p`/`strong`/`em`/`ul`/`ol`/`li`/`a`/`h1~h6`/`blockquote`/`code`/`pre`/`hr` 등 허용 태그만 남기고 `script`, `on*` 이벤트 핸들러, `javascript:` 스킴 등은 제거). RA(사람)가 작성하는 콘텐츠지만 XSS 벡터를 원천 차단하기 위해 화이트리스트를 적용합니다.

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
    → 유사도 ≥ 0.82 : 관련 기사로 판단 (그룹핑 로직 자체는 미구현)
```

임계값 0.82는 실제 데이터 기준으로 조정 가능합니다. 이 인프라는 현재 research-analyst 에이전트의 온디맨드 작업에는 쓰이지 않습니다(배치를 직접 읽고 판단) — 나중에 PE가 상시 자동 클러스터링 파이프라인을 만들 때 사용하기 위해 남겨둔 것입니다.

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

**현재 실제로 자동화된 작업은 "뉴스 수집" 하나뿐입니다.** `services/scheduler.py`의 `_job_collect()`가 `collect_naver()`를 호출해 `CollectionLog`를 남기는 것까지만 구현돼 있습니다. `register()`는 `schedule.schedule_type`을 보지 않고 항상 `_job_collect`를 등록하므로, `Schedule.schedule_type`에 `"report"` 타입으로 등록해도 실제로 실행되는 것은 수집 잡입니다 — `"report"` 전용 잡은 아직 구현돼 있지 않습니다.

`start()`는 `runserver` 기동 시 `Schedule.objects.filter(is_active=True)`를 전부 조회해 각 레코드를 `register()`로 APScheduler 잡에 등록합니다. **현재 활성 수집 스케줄이 실제로 가동 중입니다**: `Schedule` pk=1, cron `0 9 * * 1-5`(평일 9시), `is_active=True`. 즉 "설정하면 된다"가 아니라 "설정돼서 돌고 있다" 상태이며, 스케줄러가 in-process(APScheduler, `runserver`와 함께 기동)라 서버가 꺼져 있으면 9시에 실행되지 않는다는 점에 유의해야 합니다.

### 실행 스케줄

| 작업 | 상태 | 주기(설정 시) |
|------|------|------|
| 뉴스 수집 | **구현 완료·자동 실행** | 평일 9시(`0 9 * * 1-5`, 현재 활성 pk=1) 등 등록된 cron대로 |
| 관련성 판정·삭제, 인사이트 작성, 보고서 편집 | research-analyst 에이전트가 온디맨드 세션에서 수동 수행 (자동 분류 단계 없음) | 자동 스케줄 없음 |
| 임베딩 생성 | 코드는 있으나(`services/embedder.py`) 트리거(버튼·스케줄) 없음 | — |
| Slack 발송 | 미구현 | — |

### Schedule 모델 연동

`Schedule` 모델의 `is_active` 값을 읽어 실행 여부를 제어합니다. SET-004 화면에서 켜고 끌 수 있습니다. (현재는 `schedule_type` 값과 무관하게 등록된 모든 활성 스케줄이 수집 잡으로 동작)

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
