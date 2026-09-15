# RAG 구현 비교: LangChain과 직접 구현

AI Market Watch에 RAG를 넣을 때 **LangChain을 쓸 것인가**를 판단하기 위한 문서다. 색인 4단계와 검색 3단계를 각각 두 방식으로 써 놓고 비교한다.

- 작성 2026-09-15.
- 🔴 **결론은 「지금은 직접, 대화형 검색 시점에 리트리버만 재판단」이다.** 근거는 마지막 절에 있다.
- 코드는 **설명용 예시**다. 실제 구현은 PE가 실호출로 확인하고 짠다.

---

## 0. 전제 — 지금 무엇이 서 있는가

| 층 | 상태 | 실측 |
|---|---|---|
| 벡터 저장소 | 구축됨 | pgvector 확장, `Embedding` 모델 |
| 차원 | 1024 고정 | `VectorField(dimensions=1024)` |
| 임계값 | 0.82 | `EMBEDDING_SIMILARITY_THRESHOLD` |
| 임베딩 생성기 | 있으나 Voyage | `services/embedder.py` |
| 🔴 실제 벡터 | **0건** | `Embedding.objects.count() == 0` |
| 🔴 LangChain | **import 0건** | `requirements.txt`에 5종 고정, 코드 사용 없음 |

**모델 정의가 이렇다.**

```python
class Embedding(models.Model):
    news = models.OneToOneField(News, on_delete=models.CASCADE, related_name="embedding")
    vector = VectorField(dimensions=1024)
    model = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
```

⚠️ **`OneToOneField`와 `CASCADE`가 이 문서 전체에서 반복해 등장한다.** 두 방식의 차이가 대부분 여기서 갈린다.

---

## 1. 색인 4단계

### 1-1. Load

원본을 가져오는 단계다.

**직접**

```python
from apps.news.models import News

targets = News.objects.verified().filter(embedding__isnull=True)
```

**LangChain**

```python
from langchain_community.document_loaders import DataFrameLoader
# 또는 커스텀 BaseLoader를 상속해 Django ORM을 감싼다

docs = loader.load()   # Document(page_content=..., metadata=...)
```

| | 직접 | LangChain |
|---|---|---|
| 소스 | Django ORM | `DocumentLoader` 100종 이상 |
| 우리에게 필요한 소스 수 | **1개** | 1개 |
| 코드 | 한 줄 | 어댑터를 짜거나 커뮤니티 로더 사용 |

🔴 **LangChain의 Load가 빛나는 곳은 소스가 여러 종류일 때다.** PDF와 Notion과 Slack과 S3를 한 파이프라인에 넣는 경우다. **우리 소스는 DB 하나다.**

### 1-2. Split

긴 문서를 조각내는 단계다.

**우리 숫자**

| | 토큰 |
|---|---|
| 기사 한 건 평균 | 약 2,800 |
| Sonnet 컨텍스트 | 1,000,000 |
| 비율 | **0.28%** |

🔴 **쪼갤 필요가 없다. 기사 한 건이 한 조각이다.**

**RAG 교재가 Split을 강조하는 이유는 「PDF 300쪽을 넣을 수 없어서」다.** 그 전제가 우리에게 없다.

⚠️ **오히려 쪼개면 손해다.** *"이 기사 뒷부분만 검색에 걸려 맥락이 잘렸다"*가 생긴다. 판정 기준 `1-b`가 **「AI를 빼도 기사가 성립하는가」**를 묻는데, 이건 **본문 전체를 봐야 답할 수 있다.**

| | 직접 | LangChain |
|---|---|---|
| 필요 여부 | **불필요** | 불필요 |
| 쓴다면 | `News.body` 그대로 | `RecursiveCharacterTextSplitter` |

**두 방식 모두 이 단계를 건너뛴다. 차이가 없다.**

### 1-3. Embed

텍스트를 벡터로 만드는 단계다.

**직접 (Bedrock)**

```python
import json, boto3
from django.conf import settings

_client = boto3.client("bedrock-runtime", region_name=settings.AWS_DEFAULT_REGION)

def embed_text(text: str) -> list[float]:
    resp = _client.invoke_model(
        modelId=settings.BEDROCK_EMBEDDING_MODEL,
        body=json.dumps({"inputText": text}),
    )
    return json.loads(resp["body"].read())["embedding"]
```

**LangChain**

```python
from langchain_aws import BedrockEmbeddings   # 🔴 지금 안 깔려 있음

emb = BedrockEmbeddings(model_id=MODEL_ID, region_name="ap-northeast-2")
vectors = emb.embed_documents([text])
```

| | 직접 | LangChain |
|---|---|---|
| 코드량 | 약 10줄 | 3줄 |
| 추가 패키지 | 0 (boto3는 이미 있음) | 🔴 **`langchain-aws`** |
| 모델 교체 | 상수 하나 | 클래스 교체 |
| 응답 원문 접근 | ✅ 직접 | 래퍼가 정규화 |

⚠️ **여기는 LangChain이 실제로 더 짧다.** 다만 **차이가 7줄이고 패키지가 하나 는다.**

### 1-4. Store

벡터를 저장하는 단계다. **🔴 두 방식의 차이가 가장 큰 곳이다.**

**직접**

```python
from apps.news.models import Embedding

Embedding.objects.update_or_create(
    news=news,
    defaults={"vector": vec, "model": MODEL_ID},
)
```

**LangChain**

```python
from langchain_postgres import PGVector   # 🔴 지금 안 깔려 있음

store = PGVector(embeddings=emb, connection=DSN, collection_name="news")
store.add_texts([text], metadatas=[{"news_id": news.pk}])
```

🔴 **LangChain의 `PGVector`는 자기 테이블을 따로 만든다.**

```
langchain_pg_collection
langchain_pg_embedding
```

**우리 `Embedding` 테이블을 쓰지 않는다.** 그래서 이런 차이가 생긴다.

| | 직접 (`Embedding`) | LangChain (`PGVector`) |
|---|---|---|
| News와의 연결 | ✅ `OneToOneField` | 🔴 메타데이터 JSON의 `news_id` |
| 기사 삭제 시 | ✅ `CASCADE`로 **같이 지워짐** | 🔴 **고아 벡터가 남음** |
| Django ORM 조인 | ✅ 가능 | 🔴 불가 |
| 마이그레이션 관리 | ✅ Django | 🔴 LangChain이 자기 스키마를 만듦 |
| 중복 방지 | ✅ `OneToOne` 제약 | 직접 관리 |

### 🔴 고아 벡터가 왜 치명적인가

**2026-09-15 하루에 기사 122건을 삭제했다.** 삭제는 `ExcludedURL`을 만들어 재수집조차 막는 동작이다.

```
직접        News 삭제 → Embedding도 CASCADE로 삭제 → 검색에 안 걸림
LangChain   News 삭제 → langchain_pg_embedding에 122개가 그대로 남음
            → 🔴 관련 없다고 버린 기사가 대화형 검색 답변의 근거로 나온다
```

**막으려면 삭제할 때마다 벡터스토어에서도 지우는 코드를 따로 짜야 한다.** 그 코드를 빼먹어도 **에러가 나지 않는다.** 이 프로젝트가 반복해서 겪은 **「어겨도 에러가 안 나는」** 유형이다.

---

## 2. 검색 3단계

### 2-1. Retrieve

질문에 가까운 문서를 찾는 단계다.

**직접**

```python
from pgvector.django import CosineDistance
from apps.news.models import Embedding, News

qvec = embed_text(question)

rows = (
    Embedding.objects
    .filter(news__in=News.objects.verified())        # 🔴 검증 게이트가 조인 한 줄
    .annotate(distance=CosineDistance("vector", qvec))
    .filter(distance__lt=0.18)                       # 유사도 0.82
    .select_related("news")
    .order_by("distance")[:10]
)
```

**LangChain**

```python
verified_ids = list(News.objects.verified().values_list("pk", flat=True))   # 🔴 먼저 전량을 뽑아야 함

docs = store.similarity_search_with_score(
    question, k=10,
    filter={"news_id": {"$in": verified_ids}},
)
```

| | 직접 | LangChain |
|---|---|---|
| 검증 게이트 | ✅ **SQL 조인** | 🔴 id 목록을 파이썬으로 뽑아 필터에 넣음 |
| 규모가 커지면 | 그대로 동작 | 🔴 id 목록 자체가 커짐 |
| 게이트를 빼먹으면 | 미검증이 샘 | 미검증이 샘 |
| MMR | 직접 구현 | ✅ `search_type="mmr"` 한 줄 |
| 하이브리드 검색 | 직접 구현 | ✅ `EnsembleRetriever` |
| 리랭킹 | 직접 구현 | ✅ `ContextualCompressionRetriever` |

🔴 **이 단계가 LangChain이 유일하게 확실히 이기는 곳이다.**

**세 기법이 무엇인지는 아래와 같다.**

| 기법 | 무엇을 푸나 |
|---|---|
| **MMR** | 상위 N건이 거의 같은 기사로 채워지는 것을 막는다. 관련성은 높으면서 서로는 다른 것을 섞어 뽑는다 |
| **하이브리드** | 벡터는 뜻을 찾고 키워드는 글자를 찾는다. 둘을 합친다. 🔴 벡터만 쓰면 `KB금융지주`를 찾는데 `신한금융지주`도 가깝다고 본다 |
| **리랭킹** | 1차로 벡터로 넓게 건지고, 2차로 질문과 문서를 **같이 넣어** 쌍으로 채점해 재정렬한다 |

⚠️ **우리 도메인은 고유명사와 숫자가 중요해서 하이브리드가 특히 유효할 수 있다.**

### 2-2. Augment

찾은 것을 프롬프트에 끼우는 단계다.

**지금 `services/llm.py`가 이렇게 조립한다.**

```python
def _build_user_message(news) -> str:
    return (
        f"제목: {news.title}\n"
        f"현재 태깅된 기업: {', '.join(org_names) or '없음'}\n"
        f"현재 태깅된 기술 주제: {', '.join(tech_names) or '없음'}\n"
        f"매칭된 수집 키워드: {', '.join(news.matched_keywords) or '없음'}\n\n"
        f"본문:\n{news.body}"
    )
```

**직접 — 검색 결과를 끼우면 한 줄이 는다.**

```python
        f"매칭된 수집 키워드: ...\n\n"
        f"관련 기사:\n{retrieved_text}\n\n"      # ← 이 줄
        f"본문:\n{news.body}"
```

**LangChain**

```python
from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_messages([("system", SYSTEM), ("human", "{context}\n\n{question}")])
```

| | 직접 | LangChain |
|---|---|---|
| 조립 자리 | ✅ 함수 하나 | `PromptTemplate` |
| 검색 결과 추가 | **한 줄** | 템플릿 변수 |
| 🔴 캐시 제어 | ✅ `cache_control` `ttl: 1h` 직접 | 래퍼마다 다르게 감쌈 |

⚠️ **조립 자리가 함수 하나로 모여 있어서 직접 방식의 비용이 낮다.** 프롬프트가 여기저기 흩어져 있었다면 얘기가 달랐다.

### 2-3. Generate

LLM이 답하는 단계다.

**직접 (지금)**

```python
response = client.messages.create(
    model=settings.BEDROCK_MODEL_FAST,
    max_tokens=2000,
    system=[{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    }],
    messages=[{"role": "user", "content": _build_user_message(news)}],
    output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
)
usage = response.usage      # 🔴 cache_read_input_tokens 를 직접 읽어 비용을 잰다
```

**LangChain**

```python
from langchain_aws import ChatBedrock

llm = ChatBedrock(model_id=MODEL_ID)
answer = llm.invoke(prompt)
```

| | 직접 | LangChain |
|---|---|---|
| 1시간 캐시 TTL | ✅ 직접 지정 | 표준 인터페이스에 없음 |
| 구조화 출력 | ✅ `output_config.format` | 래퍼마다 다름 |
| 🔴 `cache_creation_input_tokens` | ✅ 그대로 읽음 | 정규화하며 사라지거나 이름이 바뀜 |
| `global.` 접두사 | ✅ 상수로 관리 | 래퍼가 정규화하며 어긋날 수 있음 |

### 🔴 이 프로젝트가 실측으로 알아낸 것들

```
AnthropicBedrockMantle은 서울 리전에 엔드포인트가 없다
모델 ID에 global. 접두사가 필수다
count_tokens가 Bedrock에서 지원되지 않는다
캐시 읽기가 실제로 몇 토큰인지는 응답 usage로만 안다
```

**전부 한 층 아래를 직접 보고 알아냈다.** 래퍼가 있었으면 **「래퍼 문제인지 Bedrock 문제인지」부터 갈라야** 했다.

⚠️ **`count_tokens`가 안 되므로 비용을 재는 유일한 수단이 응답 `usage`다.** 그걸 가리는 층은 이 프로젝트에서 값이 비싸다.

---

## 3. 종합

### 단계별 승패

| 단계 | 유리한 쪽 | 근거 |
|---|---|---|
| 1 Load | 직접 | 소스가 DB 하나. 로더 다양성이 무의미 |
| 2 Split | 무승부 | 양쪽 다 건너뜀 |
| 3 Embed | LangChain 소폭 | 7줄 짧음. 대신 패키지 1개 증가 |
| 4 Store | 🔴 **직접 압도** | 고아 벡터, ORM 조인, CASCADE |
| 5 Retrieve | 🔴 **LangChain 압도** | MMR, 하이브리드, 리랭킹 |
| 6 Augment | 직접 소폭 | 조립 자리가 함수 하나 |
| 7 Generate | 🔴 **직접 압도** | 캐시와 usage 세부 |

### 패키지

| | 필요한 것 |
|---|---|
| 직접 | 0개 추가 (`boto3`, `pgvector`, `anthropic` 이미 있음) |
| LangChain | 🔴 **7개** (기존 5개 + `langchain-aws` + `langchain-postgres`) |

⚠️ **지금 깔린 5개 중 대부분은 쓸 일이 없다.** `langchain-anthropic`은 직접 API용이라 Bedrock에 안 쓰고, `langchain-text-splitters`는 Split을 건너뛰므로 안 쓴다.

---

## 4. 🔴 결론

### 지금은 직접 구현한다

**근거 셋이다.**

| # | 근거 |
|---|---|
| ① | **삭제가 일상이다.** 2026-09-15 하루에 122건. LangChain 벡터스토어면 고아 벡터가 계속 쌓이고, 지우는 코드를 빼먹어도 에러가 안 난다 |
| ② | **검증 게이트가 제품의 핵심이다.** 조인으로 걸어야 새지 않는다. id 목록을 파이썬으로 뽑는 방식은 규모가 커지면 무너진다 |
| ③ | **Bedrock 고유 값을 잰다.** `count_tokens`가 안 되므로 응답 `usage`가 비용을 재는 유일한 수단이다 |

### 나중에 다시 판단한다

| 언제 | 무엇을 |
|---|---|
| MMR, 하이브리드, 리랭킹이 필요해질 때 | 🔴 리트리버만 LangChain으로 |
| 멀티턴 대화 맥락 관리가 필요해질 때 | 같음 |

**그 시점은 「대화형 검색」을 만들 때다.** 유사도 그래프만 만들 거면 **상위 N건과 임계값 0.82**로 끝나 필요 없다.

### 🔴 뒤집더라도 지킬 것

**체인과 에이전트 추상화는 쓰지 않는다.**

**LLM이 스스로 도구를 불러 DB를 바꾸면 휴먼 인 더 루프를 우회한다.** 이 제품의 핵심 설계가 **「버튼 → LLM 판정 → 제안 → 사람이 확정」**인데, 에이전트 추상화는 그 사람 자리를 건너뛴다.

**리트리버까지만 쓰고 판정과 확정은 지금처럼 명시적으로 둔다.**

### 지금 안 해도 나중에 못 하게 되는가

**아니다.**

```
임베딩은 벡터일 뿐이라 누가 만들었든 LangChain이 읽는다
pgvector는 LangChain이 지원하는 벡터스토어다
나중에 리트리버만 얹어도 쌓아 둔 벡터가 그대로 쓰인다
```

🔴 **다만 「지금부터 벡터를 쌓는 것」은 미루면 안 된다.** 나중에 RAG를 켜는 날 과거 기사 임베딩이 없으면 그날 전량을 소급 생성해야 하고, **그사이 삭제된 기사는 `DeletedNewsRecord`에서 본문을 되살려야 한다.**

---

## 더 알아보기

- [`docs/planning.md`](./planning.md) 「궁극 방향」 절 — 실행 화면은 공정이고 대화형 검색과 MCP가 출구다
- [`docs/architecture.md`](./architecture.md) — 시스템 구성과 외부 의존
- [`CLAUDE.md`](../CLAUDE.md) — 검증 게이트와 휴먼 인 더 루프
