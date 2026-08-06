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
| uid | UUIDField | 공개 식별자 (`default=uuid.uuid4`, unique·db_index). URL 노출 시엔 shortuuid 인코딩이 아니라 `UUIDField` 자체를 저장하고, URL 표시만 커스텀 컨버터(`config/converters.py`)로 shortuuid 형태로 인코딩합니다. |
| title | CharField(500) | 제목 |
| url | URLField | 원문 URL |
| url_hash | CharField(64) | URL SHA-256 해시 (중복 제거) |
| body | TextField | 본문 |
| image_url | URLField(null) | 썸네일 URL (없으면 null) |
| source_type | CharField | 자유 텍스트 (choices 제약 없음, 현재는 `naver_news`만 사용) |
| published_at | DateTimeField | 발행일 |
| collected_at | DateTimeField | 수집일 |
| status | CharField(10, choices) | 검증 게이트 상태(2026-08-04 도입). `"미검증"`(default) / `"검증됨"` 2단계뿐, "보류" 없음. **default는 반드시 `"미검증"`** — `"검증됨"`으로 두면 신규 수집분이 자동으로 게이트를 통과해 정책이 무력화된다. |
| verified_at | DateTimeField(null) | RA가 배치를 `"검증됨"`으로 전환한 시각. 기존 데이터는 백필하지 않음(모르는 값을 지어내지 않는 원칙) — `None`이면 "아직 검증 전환된 적 없음"을 뜻하는 정확한 값. |
| organizations | ManyToManyField(Organization) | 수집 시 별칭 매칭으로 자동 연결되는 기업 (related_name="news") |
| tech_topics | ManyToManyField(TechTopic) | 수집 시 별칭 매칭으로 자동 연결되는 기술 주제 (related_name="news") |

**검증 게이트 — `News.objects.verified()`**: `status="검증됨"`만 반환하는 QuerySet 메서드(`NewsQuerySet.verified()`, `apps/news/models.py`). ALL-001 핵심 지표 3종·최신 뉴스, NEWS-001 목록(`total_count` 포함), NEWS-002 상세(미검증은 직접 접근 시 404), GRAPH-001 노드·엣지·양쪽 패널 — `News`를 뷰가 스스로 쿼리하는 "직접 조회" 경로는 전부 이 메서드를 거친다. 반대로 `Insight.news`·`Report.news`·`OrgRelation.news`(RA가 근거로 직접 골라 연결한 명시 M2M), `report_extras`의 `참고: <uid>` 해석 경로, 사이드바 "마지막 수집"(`apps/dashboard/context_processors.py`, 뉴스 노출이 아니라 파이프라인 생존 신호)은 게이트를 의도적으로 적용하지 않는다. 상세는 `docs/planning.md` "검증 게이트: 미검증 뉴스는 화면에 노출하지 않는다" 절 참고.

**대체된 종전 원칙(중요)**: 이 정책 도입 전까지는 "삭제되지 않고 남아 있다 = 관련 있음"이 설계 원칙이었다(그래서 `is_relevant` 같은 상태 플래그가 없었다). 이 원칙은 "판정 이후"의 정적 상태만 보고 "수집됐지만 아직 RA가 판정하지 않은" 시간 구간을 놓쳐, 그 구간의 뉴스가 판정 완료 뉴스와 DB에서 완전히 동일하게 보이는 문제가 있었다(실제 사례: 2026-08-04 수집 60건 중 52건이 노이즈였는데 RA 처리 전까지 60건 전부가 노출됨). 지금은 **"검증 완료로 표시됐다 = 관련 있음"**으로 대체됐다 — 삭제는 여전히 노이즈 제거의 실행 수단이지만, 남아 있다는 사실만으로는 관련 있음을 뜻하지 않는다.

---

**ExcludedURL** — 삭제된 뉴스의 URL 해시 (재수집 방지, **스키마 동결**)

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| url_hash | CharField(64, unique) | 삭제된 뉴스의 URL 해시 |
| deleted_at | DateTimeField | 삭제 시각 |

뉴스 삭제 시 `url_hash`를 여기에 기록. `collect_naver()`가 수집 시 이 테이블도 확인해서 한 번 삭제한 URL은 다시 저장하지 않음(재수집 차단 핫패스). **재수집 차단 전용이며 판정 근거는 담지 않는다 — 판정 근거는 아래 `DeletedNewsRecord`가 별도로 담당한다.** `services/collector.py`가 기사마다 조회하는 핫패스라 **필드·제약 추가를 일절 금지**한다(`docs/planning.md` "판정 기록 보존 정책" 3번, 2026-08-04 확정). `DeletedNewsRecord`와는 `url_hash`로만 느슨하게 연결되며 FK도 unique 제약도 없다.

---

**DeletedNewsRecord** — 삭제된 뉴스의 판정 기록 (2026-08-04 도입, `docs/planning.md` "판정 기록 보존 정책: 버린 것도 자산이다")

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| title / url / url_hash / body / source_type / published_at / collected_at | - | 삭제 시점 `News` 필드를 그대로 복사한 원문 스냅샷. `body`는 수집 시점 크롤링본 그대로(요약·가공 안 함), 외부 공개·재발행 금지 |
| criterion_code | CharField(20, blank) | 적용 판정 기준 코드. **고정 choices 아님** — `1-a`/`1-b`/`2`/`3`/`4`/`5`/`S-KLS`/`기타` 권장 어휘를 `help_text`로 안내(기준이 계속 개정되므로 enum으로 박지 않음) |
| reason | TextField(blank) | 삭제 사유 1~2문장 자유 서술 |
| judged_by | CharField(30) | 판정 주체. 권장 어휘: `RA`(default) / `사용자(화면 삭제)` / `소급 정비` / `자동 판정`(향후) |
| organizations_snapshot / tech_topics_snapshot | JSONField(list) | 삭제 시점 연결돼 있던 `Organization.name`/`TechTopic.name` 목록. M2M은 `news.delete()`와 함께 사라지므로 이름을 복사해 둔 것 — collector 과다태깅 실패 사례가 삭제분에 몰려 있어 옵션 B 핵심주체 판별의 직접 재료 |
| judged_at | DateTimeField(auto_now_add) | 기록 시각 |

`url_hash`는 `ExcludedURL`과 달리 **unique가 아니다** — 같은 URL이 재수집·재판정되면 여러 건이 쌓일 수 있는 **이력**이기 때문이다. `ExcludedURL`(존재 여부만 의미 있는 재수집 차단 인덱스, 스키마 동결)과는 성격이 반대라 별도 모델로 분리했다.

**비노출 계약(검증 게이트보다 강함)**: 어떤 뷰·컨텍스트 프로세서·집계에서도 조회하지 않는다. Django admin에도 등록하지 않는다. 조회 화면도 없다 — 유일한 소비자는 사람(RA·PE)과 옵션 B 착수 시점의 PE(ORM으로 직접 읽음)다. 무기한 보관하며 자동 정리 잡은 없다(재검토 시점은 "옵션 B 자동 판정이 로컬 검증을 통과한 시점").

**786건 소급 백필 없음**: 2026-08-04 이전에 `ExcludedURL`만 남기고 삭제된 786건은 원문 역추적이 불가능해(URL 해시뿐) 복구하지 않는다. 확정 손실로 기록하고 넘어간다.

---

**TagCorrectionRecord** — 살아남은 뉴스의 태깅 교정 이력 (2026-08-04 도입, `docs/planning.md` "판정 기록 보존 정책" 4번, P1)

`DeletedNewsRecord`와 역할이 다르다 — 그건 "삭제된 뉴스가 삭제 시점에 갖고 있던 태그 스냅샷"이고, 이건 "삭제되지 않고 살아남은 뉴스에서 사람이 손으로 고친 태그 내역"이다. 대상 뉴스는 DB에 그대로 남으므로 "현재 태그"는 `News.organizations`/`News.tech_topics`로 언제든 조회 가능하고, 이 모델이 남기는 건 소실되는 "뗀/붙인 태그"라는 차분뿐이다.

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| news | ForeignKey(News, on_delete=CASCADE) | 교정 대상 뉴스 (related_name="tag_corrections") |
| axis | CharField(20, choices) | `organization` / `tech_topic` |
| action | CharField(10, choices) | `add` / `remove` |
| target_name | CharField(200) | 대상 `Organization.name`/`TechTopic.name`. FK가 아니라 이름 문자열 — `DeletedNewsRecord`의 태그 스냅샷과 같은 이유로, 대상이 나중에 개명·비활성화돼도 교정 당시 기록이 그대로 남는다 |
| reason | TextField(blank) | 교정 사유, 짧게(1문장 권장) |
| judged_by | CharField(30) | 판정 주체. `DeletedNewsRecord`와 동일 어휘(값을 직접 참조): `RA`(default) / `사용자(화면 삭제)` / `소급 정비` / `자동 판정`(향후) |
| corrected_at | DateTimeField(auto_now_add) | 교정 시각 |

**`correct_news_tag()`(`apps/news/services.py`) 헬퍼로만 생성한다** — `news.organizations.add()/remove()`를 직접 호출하지 않는다. `target`(Organization 또는 TechTopic 인스턴스)의 타입으로 축을 자동 판별해 M2M 변경과 기록 생성을 한 트랜잭션으로 묶는다. RA의 배치 처리(Django shell)뿐 아니라 NEWS-002 화면의 기업 태그 추가/제거 버튼(`apps/news/views.py: news_org_add`/`news_org_remove`)도 이 헬퍼를 거치도록 배선돼 있다(화면 경로는 `judged_by=사용자(화면 삭제)`, 사유는 빈 값 허용 — `DeletedNewsRecord`의 화면 삭제 경로와 동일한 취급).

**비노출 계약(검증 게이트보다 강함)**: `DeletedNewsRecord`와 동일 — 어떤 뷰·컨텍스트 프로세서·집계에서도 조회하지 않는다. Django admin에도 등록하지 않는다. 유일한 소비자는 사람(RA·PE)과 옵션 B 착수 시점의 PE(핵심 주체 vs 배경 언급 판별 로직의 명세 재료로 사용).

⚠️ **알려진 한계 — 뉴스를 삭제하면 그 뉴스의 교정 이력이 함께 사라진다 (2026-08-06 실측).** `news`가 `on_delete=CASCADE`라 `News` 행이 지워질 때 `TagCorrectionRecord`도 같이 지워진다. `DeletedNewsRecord`는 본문 스냅샷까지 복사해 보존하는데 교정 기록에는 같은 보호가 없어, **판정 기록 보존 정책이 지키려는 자산이 한쪽만 지켜지는 상태**다. 위 "유일한 소비자 = 옵션 B 착수 시점의 PE"와 정면으로 부딪힌다 — 명세 재료로 쌓는 기록인데 조용히 줄어든다.

- **손실 경로가 둘이다.** ① 사용자가 NEWS-002 화면에서 뉴스를 삭제 ② RA가 소급 재판정으로 삭제. 2026-08-06에 둘 다 실제로 발생했다(News 1306에서 3건, News 732에서 1건, 확인된 누계 **4건**). 그 이전 손실분은 흔적이 남지 않아 셀 수 없다.
- **삭제 시점에 경고가 없다.** `delete_news_with_record()`는 삭제 기록은 남기지만 교정 기록 소실은 알리지 않는다. 즉 **판정 기록을 지키려고 만든 헬퍼를 호출하는 그 자리에서 다른 기록이 사라진다.**
- **아직 고치지 않기로 했다(2026-08-06 사용자 결정).** 손실 4건 규모에서 스키마를 바꿀 만하지 않다는 판단이며, RA가 배치 보고서에 손실 카운터를 누적한다. 후보안은 `SET_NULL` + 뉴스 제목·pk 스냅샷 필드 추가다. **손실이 더 쌓이면 다시 올린다.**

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

**Report** — 주간 AI 인사이트 보고서. **자동 생성되지 않으며, RA가 `docs/planning.md`의 "주간 보고서(Report) 표준 구조"에 따라 수동으로 작성**합니다. `status`도 자동 전이되지 않고 RA가 작성을 마치면 `"done"`으로 명시적으로 바꿔야 합니다.

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| uid | UUIDField | 공개 식별자 (`default=uuid.uuid4`, unique·db_index). News.uid와 동일하게 저장 자체는 `UUIDField`이며, URL 표시만 shortuuid 커스텀 컨버터(`config/converters.py`)로 인코딩합니다. |
| period_type | CharField(10) | `daily`/`weekly`/`monthly` — choices, default `weekly` |
| date_from | DateField | 해당 기간 시작일 |
| date_to | DateField | 해당 기간 종료일 |
| title | CharField(500) | 보고서 제목 |
| overview | TextField(blank) | 주요 동향 개요 |
| content | TextField(blank) | 주요 이슈 + 시사점 |
| status | CharField(20) | `generating`(생성중, default) / `done`(완료) / `failed`(실패) — RA가 작성 완료 시 `done`으로 명시 전환 |
| slack_sent_at | DateTimeField(null) | Slack 발송 시각 |
| news | ManyToManyField(News, through=ReportNews) | 근거 News |
| created_at | DateTimeField | |

`Meta.unique_together = ("period_type", "date_from")`, `ordering = ["-date_from"]`.

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

`setting.views.slack`은 `channel_name`/`webhook_url`/`is_active` **설정 저장만** 담당합니다. 실제 webhook으로 POST를 보내는 발송 코드는 미구현이며, 당분간 구현하지 않기로 확정된 상태입니다.

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

**OrgRelation** — 지식그래프(GRAPH-001) 2단계, 기업 쌍(엣지)의 관계 라벨. research-analyst가 근거뉴스를 읽고 수동으로 채우며(LLM 자동 분류 아님), 엣지당 라벨은 정확히 1개(자유 텍스트, M2M 아님)입니다.

| 필드 | 타입 | 설명 |
|------|------|------|
| id | AutoField | PK |
| org_a | ForeignKey(Organization, related_name="relations_as_a") | 정규화된 쌍의 낮은 pk 쪽 |
| org_b | ForeignKey(Organization, related_name="relations_as_b") | 정규화된 쌍의 높은 pk 쪽 |
| label | CharField(50) | 관계 성격 자유 텍스트(단일 값). 권장 어휘 세트(기술협업/공동개발/공급계약/지분투자/인수/합병/MOU·업무협약/파트너십)는 `docs/planning.md` "관계 라벨 권장 어휘 세트" 절 참조 |
| description | TextField(blank) | 관계 서술(선택) |
| news | ManyToManyField(News, related_name="org_relations") | 저장 시점 두 기업 교집합 뉴스(근거) |
| created_at | DateTimeField | |
| updated_at | DateTimeField | |

`Meta.unique_together = ("org_a", "org_b")`. 저장 시 `org_a.pk < org_b.pk`가 항상 성립하도록 정규화합니다 — `graph_edge_panel`이 쓰는 `sorted((pk_a, pk_b))` 규칙과 동일 계약이며, 모델 `save()`에서도 이중으로 강제합니다(`apps/setting/models.py`). 작성자 필드는 두지 않습니다(운영 주체가 사실상 RA 단독).

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
│   │   ├── models.py        # DataSource, Keyword, Prompt, Schedule, SlackConfig, CollectionLog, LLMLog, Organization, TechTopic, OrgRelation
│   │   ├── views.py
│   │   └── urls.py
│   └── graph/               # 지식그래프 (GRAPH-001)
│       ├── views.py         # graph(관계도), graph_org_panel(HTMX 패널), graph_edge_panel(엣지 근거뉴스 패널), graph_edge_label_save(관계 라벨 저장)
│       └── urls.py
│
├── services/
│   ├── collector.py         # 수집 파이프라인
│   ├── llm.py               # Claude API 연동
│   ├── embedder.py          # 임베딩 생성
│   ├── scheduler.py         # 스케줄 실행
│   └── periods.py           # 대시보드·지식그래프 공통 기간 필터 유틸
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
│       ├── _org_panel.html  # 기업 노드 클릭 시 HTMX 패널
│       └── _edge_panel.html # 엣지(기업 쌍) 클릭 시 근거뉴스 HTMX 패널
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
| `/reports/<uid>/` | 보고서 상세 (REPORT-002) — `uid`는 `shortuuid` 커스텀 컨버터(`config/converters.py`) |
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
| `/graph/?period=all\|30d\|7d` | 지식그래프 (GRAPH-001) — `period` 생략 시 `7d` |
| `/graph/orgs/<pk>/panel/?period=...` | 기업 노드 관련뉴스 패널 (HTMX 조각) |
| `/graph/edges/<pk_a>/<pk_b>/panel/?period=...` | 기업 쌍(엣지) 근거뉴스 패널 (HTMX 조각) — `pk_a == pk_b`면 404 |
| `/graph/edges/<pk_a>/<pk_b>/label/?period=...` | 관계 라벨 저장 (POST 전용) — `OrgRelation` update_or_create 후 `_edge_panel.html` 재렌더 |

---

## 기간 필터 공통 유틸 (`services/periods.py`)

대시보드(ALL-001)와 지식그래프(GRAPH-001)는 "전체 / 최근 30일 / 최근 7일" 3-옵션 기간 필터를 공유합니다(2026-07 코드리뷰로 두 앱의 중복 구현을 이 모듈로 통합). 기준 필드는 항상 `News.published_at`(발행일)이고 `collected_at`이 아닙니다.

- `VALID_PERIODS = {"all", "30d", "7d"}`
- `resolve_period(request)` — `request.GET["period"]`를 검증. 없거나 유효하지 않으면 `"7d"`로 폴백.
- `period_bounds(period, today)` — `(start_date, today)`를 반환. `today`는 호출부(각 뷰)가 한 번만 계산해서 넘깁니다(뷰 안의 여러 헬퍼가 `timezone.localtime(timezone.now()).date()`를 중복 계산하지 않도록). `"7d"`→`(오늘−6일, 오늘)`, `"30d"`→`(오늘−29일, 오늘)`, `"all"`→`(None, 오늘)`.
- **"전체"(`start_date=None`)는 하한·상한 어느 쪽도 걸지 않습니다** — 즉 필터를 아예 적용하지 않습니다. 대시보드·그래프 두 화면이 같은 데이터를 두고 항상 같은 숫자를 보여줘야 한다는 "기간 정합성 계약"이 이 정의로 성립합니다.

두 앱의 `views.py`는 각각 이 세 함수를 import해서 쓰고, 앱별로 필요한 쿼리셋 적용 방식(대시보드는 `Q()` 조건부 필터, 그래프는 `.filter()` 얇은 래퍼)만 자체 헬퍼로 감쌉니다.

---

## 대시보드 집계 (ALL-001)

전체 대시보드 "핵심 지표" 3개 카드는 `apps/dashboard/views.py`의 `dashboard()`가 페이지 상단 기간 필터(전체/최근 30일/최근 7일, 기본값 최근 7일)에 맞춰 집계합니다. `period`는 `services.periods.resolve_period(request)`로, 날짜 경계는 `services.periods.period_bounds(period, today)`로 구합니다.

- **뉴스 건수 추이** (`_build_trend_points`) — 버킷 단위가 기간에 따라 가변입니다: `"7d"`/`"30d"`는 일 단위(`_build_day_buckets(today, start_date)`, 버킷 개수는 `(today - start_date).days + 1`로 유도), `"all"`은 데이터 전체 기간 길이에 따라 주 단위 또는 월 단위 롤링 윈도우(`_build_rolling_buckets`, `WEEK_BUCKET_MAX_DAYS=364`일 이하면 주 단위, 초과면 월 단위)로 그립니다. 각 포인트의 SVG 좌표(`x`/`y`)와 베지어 경로 문자열(`trend_line_path`/`trend_area_path`), x축 라벨 솎아내기(`show_label`)는 모두 뷰에서 계산해 템플릿에 넘깁니다. 점(dot) 크기 축소 여부(`trend_dense`, 포인트 15개 초과 시 축소)도 같은 원칙으로 뷰가 계산합니다 — 템플릿은 SVG 좌표·크기 판단을 하지 않습니다.
- **기업별 건수 Top 10** (`_build_org_ranking`) — 활성(`is_active=True`) `Organization` 중 선택된 기간에 연결된 `News` 건수가 1건 이상인 기업을 건수 내림차순으로 최대 10개까지 집계합니다. 기업별로 최근 뉴스 최대 5건을 함께 담아 호버 팝오버에 사용합니다.
- **기술 주제별 언급 건수** (`_build_tech_topic_counts`) — 활성 `TechTopic` 중 선택된 기간에 연결된 `News` 건수가 1건 이상인 주제를 건수 내림차순으로 집계합니다(0건 주제는 제외). 기업별 Top 10과 동일하게 최근 뉴스 최대 5건을 함께 담습니다.

세 지표 모두 `News.organizations`/`News.tech_topics` M2M(수집 시 `services/collector.py`의 별칭 매칭으로 자동 연결)을 근거로 집계하며, 별도의 캐시·배치 집계 테이블 없이 매 요청마다 실시간으로 계산합니다. 기간 선택은 `<a href="?period=...">` 전체 페이지 GET 재로드 방식입니다(HTMX 부분 스왑 아님).

**주요 이슈·최신 뉴스 카드(기간 필터 미적용)**: "핵심 지표" 3개 카드와 달리 주요 이슈·최신 뉴스 카드는 상단 기간 필터(전체/최근 30일/최근 7일)의 영향을 받지 않습니다 — 기간 선택은 핵심 지표 전용이며, 주요 이슈·최신 뉴스는 항상 전체 데이터 기준 최신 상태를 보여줍니다. 주요 이슈는 `Insight`를 근거 뉴스 최신 발행일(`latest_news_at = Max("news__published_at")`, `nulls_last=True`, `-pk` tie-breaker) 내림차순으로 최대 20건(`[:20]`), 최신 뉴스는 `News`를 `published_at` 내림차순으로 최대 30건(`[:30]`) 가져옵니다. 두 카드 모두 `max-h-[40rem]`으로 카드 높이를 제한하고 내부 리스트에 `.dashboard-scroll`(커스텀 스크롤바 스타일) 클래스로 스크롤을 겁니다.

**정보 툴팁**: 뉴스 건수 추이·기업별 건수 Top 10·기술 주제별 언급 건수·주요 이슈·최신 뉴스 각 카드 제목 옆에 `{% info_tooltip %}` 커스텀 템플릿 태그(`apps/dashboard/templatetags/dashboard_extras.py`)로 "데이터·기준" 설명 툴팁을 붙입니다. 문구는 `apps/dashboard/tooltips.py`의 `INFO_TOOLTIPS` 딕셔너리(키 예: `"dashboard.trend"`, `"dashboard.insights"`)에서 관리하며, `templates/components/_info_tooltip.html`을 `inclusion_tag`로 렌더링합니다.

---

## 지식그래프 (GRAPH-001)

`apps/graph/views.py`가 기업(`Organization`) 간 관계를 D3.js force-directed 그래프로 시각화합니다. 대시보드와 동일한 3-옵션 기간 필터(전체/최근 30일/최근 7일, 기본값 최근 7일)를 상단 세그먼트 pill로 제공하며, `graph`/`graph_org_panel`/`graph_edge_panel` 세 뷰 모두 `services.periods.resolve_period`/`period_bounds`로 같은 기간 정의를 공유합니다("기간 정합성 계약" — 세 뷰가 다른 필터 로직을 쓰면 캔버스·패널 숫자가 어긋날 수 있음).

**2026-07-31 "옵션 a" 확정으로 엣지·노드·라벨 표시 방식이 전면 바뀌었습니다** (근거: `docs/planning.md` "지식그래프 축 1 확정: 옵션 a" 절). 과거의 "공동언급 전수 계산 → 실존 엣지에 라벨을 사후로 얹기" 방식(itertools.combinations 전수 조합 + `has_label` 시각 채널 + 점선/실선 이중 표기)은 폐기되고, 아래 방식으로 대체됐습니다.

- **엣지 존재 게이트 = `OrgRelation`(라벨) 존재 여부입니다.** `graph()` 뷰는 `OrgRelation.objects.select_related("org_a", "org_b").all()`을 순회해 양 끝이 모두 활성(`is_active=True`) 기업이고 `ALLOWED_TYPE_PAIRS`(`{금융사, AI}`, `{보험사, AI}`)를 통과하는 관계만 골라 `relations`로 추립니다. **공동언급만 있고 `OrgRelation` 라벨이 없는 기업 쌍은 엣지를 아예 만들지 않습니다** — `itertools.combinations`로 모든 쌍을 전수 계산하던 옛 로직은 폐기됐고, 이제 `labeled_pairs`(라벨 있는 쌍의 집합) 자체가 엣지 후보 전체입니다.
- **노드 union** — `orgs`는 (선택 기간에 연결된 `News`가 1건 이상인 활성 기업) **∪** (라벨 엣지 양끝에 등장하는 활성 기업, `Q(news_count__gt=0) | Q(pk__in=labeled_org_pks)`)입니다. 라벨 엣지의 상대편 기업은 선택 기간에 뉴스가 0건이어도 노드로 포함됩니다 — 그래야 라벨 엣지가 참조하는 노드가 캔버스에 없는 "떠다니는 엣지" 상태가 생기지 않습니다. `symbolSize`는 기존과 동일하게 `news_count`에 비례해 `max(14, min(40, 14 + news_count * 2))`(0건이면 최소 14 하한)로 계산합니다. `category`는 `org_type`(금융사/보험사/AI)을 인덱스(0/1/2)로 매핑합니다.
- **라벨 엣지는 기간과 무관하게 상시 노출됩니다.** `edges` 리스트는 `edge_weights`(기간 내 실제 공동언급 건수 집계)를 순회하지 않고 `labeled_pairs`를 직접 순회해서 만듭니다 — 그래야 선택 기간에 공동언급이 0건인 라벨 엣지도 `value=0`으로 항상 노출됩니다. 굵기(`value`)만 선택 기간의 공동언급 건수를 반영합니다(`edge_weights`는 라벨 엣지 쌍(`labeled_pairs`)에 한정해 기존 `combinations` 집계 로직으로 계산). **굵기의 의미는 "관계 깊이 점수"가 아니라 "선택 기간 공동언급 빈도(활동 강도)"**입니다. 각 엣지 dict는 `{"source", "target", "value", "label"}`을 담으며, `has_label` 필드는 (모든 엣지가 항상 라벨 엣지라 무의미해져) 제거됐습니다.
- **기업 노드 패널** — 노드 클릭 시 `/graph/orgs/<pk>/panel/`(`graph_org_panel`)이 해당 기업에 연결된 선택 기간 내 `News` 최대 10건을 `graph/_org_panel.html` 조각으로 반환합니다(`total_count`가 10건 초과면 "전체 N건 중 10건" 표기). `is_active` 필터 없이 조회하므로 비활성 기업도 URL 직접 접근으로 볼 수 있고, 이 경우 "(비활성)" 배지를 표시합니다.
- **엣지(기업 쌍) 패널** — 엣지 클릭 시 `/graph/edges/<pk_a>/<pk_b>/panel/`(`graph_edge_panel`)이 두 기업 모두에 연결된 `News`(교집합, `.filter(organizations=a).filter(organizations=b)` 두 번 체이닝 + `distinct()`)를 `graph/_edge_panel.html` 조각으로 반환합니다. 쌍 교집합은 표본이 작다는 전제로 **컷오프 없이 전량 노출**합니다(노드 패널과 의도적으로 다른 정책). `pk_a`/`pk_b`는 `normalize_org_pair()`로 정규화하고, `pk_a == pk_b`(자기 자신과의 엣지)면 `Http404`를 raise합니다. `org_a`/`org_b` 중 비활성 기업이 있으면 노드 패널과 동일하게 "(비활성)" 배지를 표시합니다.
- **관계 라벨 입력·저장** — 엣지 패널 안 "관계" 블록에서 RA가 라벨(자유 텍스트, 필수, 최대 50자)과 설명(선택, 최대 300자)을 입력·수정합니다. 저장은 `/graph/edges/<pk_a>/<pk_b>/label/`(`graph_edge_label_save`, POST 전용)이 담당하며, `pk_a == pk_b`면 `graph_edge_panel`과 동일하게 `Http404`입니다. 정규화된 `(org_a, org_b)`로 `OrgRelation.objects.update_or_create(defaults={"label", "description"})`를 실행하고, `news` M2M은 선택된 기간 기준 두 기업의 교집합 뉴스(`_edge_news_queryset` 공유 — 패널에 실제로 보이는 `news_list`와 저장되는 `relation.news`가 항상 같은 쿼리에서 나오도록 강제)로 `.set()`합니다. `graph_edge_panel`과 `graph_edge_label_save`는 컨텍스트 조립 로직(`_build_edge_panel_context`)을 공유해, 저장 후 같은 `_edge_panel.html`을 재렌더링해 `#org-panel`을 교체합니다. `label`이 빈 문자열이거나 50자를 초과하면 저장하지 않고 현재 상태 그대로 재렌더링합니다(no-op, 500 방지). `graph_edge_panel`은 GET 시에도 정규화된 `(org_a, org_b)`로 `OrgRelation`을 조회해 `relation` 컨텍스트로 넘기며, 없으면 `None`(템플릿은 "관계 미분류"로 표시). 관계 라벨 운영 규칙(변천/병존/합병 3경우의 수동 처리 절차)과 권장 라벨 어휘 세트(기술협업/공동개발/공급계약/지분투자/인수/합병/MOU·업무협약/파트너십)는 `docs/planning.md`의 "관계 변천 운영 규칙"·"관계 라벨 권장 어휘 세트" 절을 참조하세요.
- **캔버스 시각 표기(`templates/graph/index.html`)** — 옵션 a에서는 `edges` 배열 자체가 이미 라벨 엣지만 담고 있으므로, 점선(`stroke-dasharray`)/실선 이중 채널과 `has_label` 필터링 분기가 모두 제거되고 **모든 엣지가 실선으로 통일**됐습니다. `edgeIdleColor`는 중립 Gray(`#898A8D`) 고정입니다 — 모든 엣지가 (금융사/보험사)-AI 연결이라 AI 노드 색(`#60269E`, Primary Violet)과 idle 색을 동일하게 두면 선과 노드가 뭉개져 보이는 문제가 있어 분리했습니다. hover/선택 강조 시(`selectNode`/`selectEdge`)에는 `#60269E`로 하드코딩 강조합니다. `edgeIdleOpacity`는 0.75, `edgeFadeOpacity`(다른 노드·엣지 강조로 톤다운될 때)는 0.15로 고정, `edgeWidth`는 `Math.max(1.5, Math.min(1 + value * 0.5, 5))`로 `value=0`이어도 최소 1.5px를 보장합니다.
  - 라벨 pill(`linkLabel`, `g.edge-label-g`)은 `has_label` 필터링 없이 **`edges` 전체에 클릭 없이 상시 렌더**됩니다 — 흰 배경(`fill: #FFFFFF`, `stroke: #60269E`) 둥근 사각형(`rx/ry: 8`) 위에 라벨 텍스트(`#60269E`, 10px, 600 weight)를 그립니다. pill 너비는 `getBBox()`로 텍스트를 실측해 최초 렌더 시 1회만 계산합니다. `toggleCategory()`로 카테고리를 숨기면 `linkLabel`도 함께 `display: none` 처리됩니다.
  - 뷰 단계에서 라벨 없는 엣지가 애초에 걸러지므로, 캔버스 상시 라벨과 엣지 클릭 시 뜨는 패널 라벨은 항상 "같은 엣지 = 같은 라벨"이라는 동일 데이터를 보여줍니다.
- **렌더링** — `templates/graph/index.html`에서 D3.js v7.8.5(CDN)로 force simulation을 구성합니다. 기간 선택은 대시보드와 동일하게 전체 페이지 GET 재로드 방식이며(D3 스크립트의 최상위 `const`/`let` 재선언 문제 회피), 노드·엣지 HTMX 호출 시 `?period=` 쿼리를 그대로 이어 붙여 캔버스와 패널이 같은 기간을 보게 합니다.

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

**별칭 매칭 경계 판정(`_contains_alias`, `services/collector.py`)**: 별칭이 텍스트 안에서 단어 경계를 지키며 등장하는지 확인하되, 경계 검사는 **alias 자신의 시작/끝 글자가 영숫자일 때만** 적용합니다. alias 자신의 경계 글자가 한글이면 그쪽 경계 검사를 생략합니다 — "NH농협캐피탈"처럼 한글 별칭("농협")이 영문 약어("NH")에 공백 없이 붙는 표기가 실제 기사에 흔한데, 텍스트 쪽 인접 글자("H")만 보고 경계를 판정하면 alias 자신은 한글인데도 매칭이 막혀버리기 때문입니다. alias가 "RAG"처럼 영문으로 시작/끝나는 경우는 기존처럼 엄격하게 경계를 검사해 "storage"/"average" 안에 우연히 낀 매칭은 계속 막습니다.

**알려진 구조적 한계 — 기업 과다태깅**: collector는 본문에 언급된 **모든 기업을 무차별 태깅**하며 "핵심 주체 vs 배경 언급"(관련성 판단 기준 1)을 구분하지 못합니다. 이는 결정론적 별칭 매칭의 구조적 한계입니다. 실례로 News 901(KB금융-구글 기사)은 본문의 경쟁사 비교 서술("신한은행은… 하나은행 역시…") 때문에 신한·하나은행이 오태깅됐습니다. 근본 해결(LLM 기반 핵심 주체 판별)은 옵션 B 코드화 과제이며, 그때까지는 RA가 배치 처리(관련성 판정·삭제) 시 기업 태깅도 함께 수동 검증·교정합니다. ⚠️ `remap_organizations()`를 실행하면 collector 로직으로 전량 재태깅되어 RA의 수동 교정이 원상복구되므로, 별칭 변경 시에만 신중히 실행하고 실행 후 RA가 교정분을 재확인해야 합니다(자세한 정책은 `docs/planning.md` 참조).

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

1. **노이즈 판정 + 삭제 + 검증 전환** — 갓 수집된 뉴스 배치를 직접 읽고 PM이 정의한 관련성 기준으로 판단합니다. 삭제는 손으로 3단계를 조합하지 않고 **`apps/news/services.py`의 `delete_news_with_record()`를 건별로 호출**합니다(일괄 `.filter(...).delete()` 금지는 그대로 유지). 이 함수가 한 트랜잭션 안에서 ① `DeletedNewsRecord` 생성 → ② `ExcludedURL.get_or_create()` → ③ `news.delete()`를 실행하며, ①이 실패하면 ②·③도 실행되지 않아 "기록 없는 삭제"가 원천적으로 불가능합니다(`docs/planning.md` "판정 기록 보존 정책" 2026-08-04 확정). **호출 시 `criterion_code`(권장 어휘: `1-a`/`1-b`/`2`/`3`/`4`/`5`/`S-KLS`/`기타`)와 `reason`(1~2문장)을 반드시 채웁니다** — 빈 값으로 지나가면 이 정책이 무력화됩니다.
   ```python
   from apps.news.models import DeletedNewsRecord
   from apps.news.services import delete_news_with_record

   delete_news_with_record(
       news,
       criterion_code="1-b",
       reason="AI는 부차 요소로만 곁들여지고 지배적 주제는 실적 발표.",
       judged_by=DeletedNewsRecord.JUDGED_BY_RA,
   )
   ```
   **기업 태깅 검증·교정도 이 단계에 편입**됩니다 — collector의 별칭 매칭이 "핵심 주체 vs 배경 언급"을 구분하지 못해 과다태깅되는 구조적 한계(5절 참고)가 있으므로, RA가 배치를 판정하면서 잘못 태깅된 `Organization`/`TechTopic` 연결도 함께 수동 검증·교정합니다. **이 교정도 `news.organizations.add()/remove()`를 직접 호출하지 않고 `apps/news/services.py`의 `correct_news_tag()`를 씁니다**(2026-08-04 도입, `docs/planning.md` "판정 기록 보존 정책" 4번, P1) — 한 번 호출로 M2M 변경과 `TagCorrectionRecord`(3절 참고) 생성이 함께 일어나, "무엇을 왜 뗐는가"라는 차분이 소실되지 않습니다.
   ```python
   from apps.news.models import TagCorrectionRecord
   from apps.news.services import correct_news_tag

   correct_news_tag(
       news, org,  # org: Organization 또는 TechTopic 인스턴스
       action=TagCorrectionRecord.ACTION_REMOVE,
       reason="한편... 경쟁사 비교 문단, 핵심 주체 아님",
   )
   ```

   **⚠️ 검증 게이트(2026-08-04 도입) — 이 단계의 필수 마지막 절차**: 예전에는 "남은 `News`는 삭제되지 않았다는 사실 자체가 관련 있음을 의미"했지만, 이 원칙은 대체됐습니다. 이제는 `News.status`가 `"검증됨"`으로 전환돼야 비로소 사용자 화면(ALL-001·NEWS-001·NEWS-002·GRAPH-001)에 노출됩니다(3절 `News` 표 참고). 삭제·태깅 교정을 배치 전체에 대해 마친 직후, 살아남은 뉴스 전부를 Django ORM으로 **한 번에** `"검증됨"`으로 전환하세요(`verified_at`도 함께 현재 시각으로 채웁니다). **부분 전환 금지(all-or-nothing)** — 배치를 끝까지 읽기 전에 일부만 공개하면 동일 사건 중복 보도 판정(관련성 기준 2번)이 뒤집혀 노출됐다 사라지는 깜빡임이 생깁니다. 세션이 중단돼 배치를 끝내지 못했다면 그 배치는 통째로 미검증 상태로 남겨 두고(= 화면에 아무것도 새로 뜨지 않음), 다음 세션에서 처음부터 다시 판정합니다. 이 전환이 빠지면 판정을 마친 뉴스도 영원히 화면에 뜨지 않습니다.
2. **관련 기사 찾기 + Insight 작성** — 남은 배치의 제목·본문을 직접 읽고(pgvector 쿼리 미사용) 같은 사건을 다루는 기사를 식별해 Django ORM으로 `Insight`(`title`/`content`/`implication`)를 작성하고 `insight.news.set([...])`로 근거 `News`를 연결합니다. 별도 그룹 테이블(과거 `IssueGroup`) 없이 `Insight` 자체가 "이 기사들 + 이 분석"의 단위입니다.
3. **주간 보고서 편집** — `Report.title`/`overview`/`content`를 편집하고 `ReportNews`로 근거 `News`를 직접 연결합니다.

모든 인사이트·보고서 문단은 실제로 연결된 `News`를 출처로 추적 가능해야 하며, 근거 없는 내용은 작성하지 않는 것이 원칙입니다 (RA 에이전트 정책).

### 보고서 마크다운 렌더링

RA가 `Report.overview`/`Report.content`에 작성하는 마크다운은 `apps/reports/templatetags/report_extras.py`의 `markdown` 커스텀 템플릿 필터로 HTML로 변환됩니다. `templates/reports/detail.html`에서 `{{ report.overview|markdown }}`/`{{ report.content|markdown }}`로 사용합니다.

- **python-markdown**(`Markdown` 패키지)으로 마크다운을 HTML로 변환(`sane_lists` 확장 사용).
- **bleach**로 변환된 HTML을 화이트리스트 방식으로 정제(`p`/`strong`/`em`/`ul`/`ol`/`li`/`a`/`h1~h6`/`blockquote`/`code`/`pre`/`hr` 등 허용 태그만 남기고 `script`, `on*` 이벤트 핸들러, `javascript:` 스킴 등은 제거). RA(사람)가 작성하는 콘텐츠지만 XSS 벡터를 원천 차단하기 위해 화이트리스트를 적용합니다.

### 이슈 카드 렌더링 (`report_issues` 필터)

RA는 `Report.content`를 `docs/planning.md`의 "주간 보고서(Report) 표준 구조"에 맞춰 작성합니다. **2026-07-31 "옵션 C" 확정으로 각 이슈(`### ` 블록) 최하단에 `참고: <uid>, <uid>` 규약 줄**(`News.uid` full UUID)을 넣는 방식이 추가됐습니다 — `apps/reports/templatetags/report_extras.py`의 `report_issues` 필터가 이 규약 줄을 파싱해 uid로 `News`를 조회하고, 이슈별 참고뉴스 리스트를 REPORT-002 상세 화면의 이슈 카드 내부에 직접 렌더링합니다.

- **계약**: `content: str` → `{"preamble": str, "issues": [{"title": str, "body": str, "news_list": [News, ...]}, ...]}`
  - 줄 시작의 `### 이슈 제목`(h3)만 이슈 구분자로 인식합니다(`#### `처럼 h4 이상은 제외, 정규식 `^###[ \t]+(?!#)(.*)$`, `re.MULTILINE`).
  - 첫 `### ` 이전 텍스트는 `preamble`로, 각 `### ` 구간은 제목(`title`)과 다음 `### `(또는 문자열 끝)까지의 나머지(raw body)로 분리됩니다.
  - **참고 줄 파싱(`_split_ref_line`)**: raw body에서 공백만 있는 줄을 건너뛰고 실제 내용이 있는 마지막 줄을 찾아 `참고[ \t]*[:：][ \t]*(.*)`(공백·전각 콜론까지 관용 허용) 패턴에 매치하는지 확인합니다. 매치하면 그 줄을 떼어낸 나머지가 `body`, 콤마로 나눈 토큰들이 uid 후보입니다. 매치하지 않으면(참고 줄이 없는 과거 데이터) `body`는 raw body 그대로, uid 토큰은 빈 리스트입니다. 이 위치 규칙 덕분에 "참고 줄을 제외한 블록의 실제 마지막 문단 = 시사점"이라는 표준 구조 식별이 참고 줄 유무와 무관하게 그대로 성립합니다.
  - **uid 해석(`_resolve_ref_news`)**: 각 토큰을 `uuid.UUID()`로 파싱 시도하고, 실패하는 토큰(오타·과거 pk 등 형식 오류)은 조용히 건너뜁니다. 파싱에 성공한 uid만 `News.objects.filter(uid__in=...)`로 일괄 조회해 존재하는 것만 남기고, 토큰이 적힌 순서를 보존해 `news_list`로 반환합니다. 참고 줄이 아예 없거나 uid가 하나도 해결되지 않으면 `news_list=[]`입니다 — 어떤 경우에도 500 에러 없이 빈 리스트로 폴백합니다.
  - `body`는 마크다운 원문 그대로 반환되며 이 필터 안에서는 HTML로 변환하지 않습니다 — 템플릿이 `|markdown` 필터를 별도로 한 번 더 통과시켜 bleach 새니타이즈를 유지합니다.
  - **폴백**: `content`가 비어 있거나 `### ` 구분자가 전혀 없는 비표준/과거 데이터는 `{"preamble": content, "issues": []}`(또는 content도 없으면 `{"preamble": "", "issues": []}`)를 반환합니다.

- **`templates/reports/detail.html`의 렌더링**: "주요 이슈" 카드에서 `{% with parsed=report.content|report_issues %}`로 파싱한 뒤,
  - `parsed.issues`가 있으면: `preamble`이 있을 때만 먼저 `|markdown`으로 렌더링하고, 이어서 이슈마다 번호 배지(`forloop.counter`)와 제목을 헤더로 갖는 회색 카드(`bg-gray-50/50` 박스)를 순서대로 렌더링합니다. 카드 본문(`issue.body`)은 기존 `|markdown` 필터를 그대로 통과시켜 h1~h6/목록/링크 등이 정상 렌더링되고 bleach 새니타이즈도 유지됩니다.
  - **각 이슈 카드 내부**에 `{% if issue.news_list %}`로 감싼 "참고 뉴스" 목록을 카드 본문 하단(`border-t`로 구분)에 렌더링합니다 — 제목과 발행일을 나열하고 각 행이 `news_detail`(NEWS-002)로 링크됩니다. `news_list`가 비어 있으면(참고 줄 없음/uid 미해결/과거 데이터) 이 블록 자체를 통째로 생략합니다.
  - `parsed.issues`가 비어 있으면(폴백): `report.content` 전체를 통짜로 `|markdown` 렌더링하는 기존 방식으로 돌아갑니다.
  - **하단 통합 "참고 뉴스" 테이블은 옵션 C에서 제거됐습니다** — 과거에는 이슈 카드에 근거 링크가 전혀 없고 상세 화면 맨 아래 별도 테이블(`report.news.all` 전체를 나열)이 근거 추적을 전담했지만, 지금은 이슈별 참고뉴스가 각 카드 안에 인라인으로 붙습니다.
  - **`Report.news` M2M은 삭제되지 않고 유지**됩니다 — 다만 역할이 "유일한 출처 채널"에서 "집계·출처추적·Slack 발송 채널"로 바뀌었습니다. `Report.news`는 각 이슈 참고 줄 uid들의 합집합에 해당하는 값으로 관리되는 것을 전제로 하지만, 화면에는 더 이상 이 M2M을 직접 나열하는 UI가 없습니다.
  - 표준 구조·참고 줄 인라인 규약(옵션 C) 자체의 정의·근거는 `docs/planning.md`의 "주간 보고서(Report) 표준 구조"·"이슈별 참고뉴스 인라인 규약" 절을 참조하세요 — 이 문서는 구현(필터·템플릿) 설명만 다룹니다.

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

`start()`는 `runserver` 기동 시 `Schedule.objects.filter(is_active=True)`를 전부 조회해 각 레코드를 `register()`로 APScheduler 잡에 등록합니다.

⚠️ **현재 로컬에서는 수집 스케줄이 돌지 않습니다 (2026-08-05 확정).** `Schedule` pk=1, cron `0 9 * * 1-5`(평일 9시)는 등록돼 있으나 **`is_active=False`**이고 `next_run_at`은 `None`입니다. **로컬 = 사람이 SET-001 "지금 수집"으로 수동 실행, 프로덕션 = SET-004에서 스케줄 재활성화**가 확정된 운영 방식입니다. 즉 **로컬에서 아침에 수집이 안 돼 있어도 버그가 아니라 정상입니다.**

**왜 이렇게 정했는가** — 스케줄러가 in-process라 `runserver` 프로세스가 09:00에 떠 있지 않으면 그날 실행이 **예약조차 되지 않습니다.** `add_job()`이 `next_run_time` 없이 등록되므로 다음 실행을 **등록 시점 기준으로** 계산하기 때문입니다. 이건 misfire가 아니라서 `misfire_grace_time`을 아무리 늘려도 소용이 없고, 실제로 2026-07-30~08-05 **5회 연속 미실행**의 원인이었습니다. 상세와 프로덕션 재활성화 체크리스트는 `docs/planning.md` "수집 실행 방식: 로컬 = 수동, 프로덕션 = 스케줄" 절을 보세요.

⚠️ **수동 수집은 `CollectionLog`를 남기지 않습니다.** SET-006 로그 화면이 비어 있어도 수집이 안 된 게 아니므로, 실제 유입은 **`News` 건수 증가**로 확인해야 합니다.

### 실행 스케줄

| 작업 | 상태 | 주기(설정 시) |
|------|------|------|
| 뉴스 수집 | **구현 완료 · 로컬은 수동 실행(pk=1 `is_active=False`), 프로덕션에서 스케줄 가동** | 평일 9시(`0 9 * * 1-5`) 등 등록된 cron대로 |
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
