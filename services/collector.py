import hashlib
import html
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime

from django.conf import settings
from django.utils import timezone

from apps.news.models import ExcludedURL, News
from apps.setting.models import CollectionLog, DataSource, Keyword, Organization, TechTopic
from services.crawler import fetch_article_body
from services.text_cleaning import clean_text_for_matching

logger = logging.getLogger(__name__)

NAVER_ENDPOINT = "https://openapi.naver.com/v1/search/news.json"


def _strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _make_url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def _parse_pub_date(pub_date_str: str):
    try:
        return parsedate_to_datetime(pub_date_str)
    except Exception:
        return None


def _call_naver_api(query: str, display: int, headers: dict, sort: str = "date") -> list:
    params = urllib.parse.urlencode({
        "query": query,
        "display": display,
        "start": 1,
        "sort": sort,
    })
    req = urllib.request.Request(f"{NAVER_ENDPOINT}?{params}", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode("utf-8")).get("items", [])


def _is_word_char(ch: str) -> bool:
    """영문자/숫자만 '경계를 깨는 문자'로 취급한다.

    "RAG"가 "storage"/"average"/"fragment" 같은 영단어 안에 우연히 끼어 매칭되는 걸 막으려면
    앞뒤 문자가 영숫자가 아닐 때만 매칭으로 인정해야 한다. 다만 한글은 "RAG는"/"RAG를"처럼
    별칭 바로 뒤에 조사가 붙는 표현이 자연스럽고, 정규식 \\b는 한글에서 경계를 제대로 못 잡기
    때문에 한글 문자는 애초에 "경계를 깨는 문자"로 취급하지 않는다(=한글 별칭은 기존처럼
    부분 문자열 매칭만 적용).
    """
    return ch.isascii() and ch.isalnum()


def _contains_alias(lower_text: str, alias: str) -> bool:
    """lower_text 안에서 alias가 단어 경계를 지키며 등장하는지 확인한다.

    lower_text는 이미 소문자로 변환된 상태여야 한다.

    경계 검사는 alias 자신의 시작/끝 글자가 영숫자일 때만 적용한다. "NH농협캐피탈"처럼
    한글 별칭("농협")이 영문 약어("NH")에 공백 없이 붙는 표기가 실제 기사에 흔한데,
    텍스트 쪽 인접 글자(예: "NH"의 "H")만 보고 경계를 판정하면 alias 자신은 한글인데도
    매칭이 막혀버린다("한글 별칭은 부분 문자열 매칭만 적용한다"는 원래 의도와 어긋남).
    alias 자신의 경계 글자가 영숫자가 아니면(=한글이면) 그 쪽 경계 검사를 생략해 이
    불일치를 없앤다. alias가 영문("RAG" 등)으로 시작/끝나는 경우는 기존처럼 엄격하게
    경계를 검사해 "storage"/"average" 안에 우연히 낀 매칭은 여전히 막는다.
    """
    if not alias:
        return False
    needle = alias.lower()
    if not needle:
        return False
    start = 0
    text_len = len(lower_text)
    needle_len = len(needle)
    needle_starts_word = _is_word_char(needle[0])
    needle_ends_word = _is_word_char(needle[-1])
    while True:
        idx = lower_text.find(needle, start)
        if idx == -1:
            return False
        before_ok = (
            idx == 0
            or not needle_starts_word
            or not _is_word_char(lower_text[idx - 1])
        )
        after_idx = idx + needle_len
        after_ok = (
            after_idx == text_len
            or not needle_ends_word
            or not _is_word_char(lower_text[after_idx])
        )
        if before_ok and after_ok:
            return True
        start = idx + 1


def _find_matching_entities(text: str, entities: list) -> list:
    """text에 별칭이 매칭되는 엔티티(Organization 또는 TechTopic) 목록을 반환한다.

    두 모델 모두 name/aliases 속성 구조가 동일해서 매칭 로직을 공용화했다.
    """
    lower_text = text.lower()
    matched = []
    for entity in entities:
        all_names = [entity.name] + list(entity.aliases or [])
        if any(_contains_alias(lower_text, alias) for alias in all_names):
            matched.append(entity)
    return matched


def _link_organizations(news: News, text: str, orgs: list[Organization]) -> None:
    # .set()을 써야 재매핑 시 더 이상 매칭되지 않는(별칭을 좁혀서 오탐이 고쳐진) 기존 태그가
    # 함께 제거된다. 최초 수집 시점엔 M2M이 빈 상태라 .add()와 동작이 동일하다.
    news.organizations.set(_find_matching_entities(text, orgs))


def _link_tech_topics(news: News, text: str, topics: list[TechTopic]) -> None:
    news.tech_topics.set(_find_matching_entities(text, topics))


def collect_naver() -> dict:
    if not settings.NAVER_CLIENT_ID or not settings.NAVER_CLIENT_SECRET:
        return {"collected": 0, "skipped_dup": 0, "skipped_filter": 0, "skipped_excluded": 0,
                "crawled": 0, "crawl_failed": 0, "errors": ["Naver API key not configured"]}

    headers = {
        "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
        "User-Agent": "AI-Market-Watch/1.0",
    }
    display = settings.NAVER_DISPLAY_PER_QUERY
    delay   = settings.NAVER_REQUEST_DELAY

    naver_source = DataSource.objects.filter(name="Naver News API", is_active=True).first()
    if not naver_source:
        return {"collected": 0, "skipped_dup": 0, "skipped_filter": 0, "skipped_excluded": 0,
                "crawled": 0, "crawl_failed": 0, "errors": ["Naver News API 비활성"]}

    orgs             = list(Organization.objects.filter(is_active=True))
    topics           = list(TechTopic.objects.filter(is_active=True))
    collect_keywords = list(Keyword.objects.filter(keyword_type=Keyword.TYPE_COLLECT, is_active=True))
    exclude_keywords = [kw.keyword.lower() for kw in Keyword.objects.filter(keyword_type=Keyword.TYPE_EXCLUDE, is_active=True)]

    stats = {"collected": 0, "skipped_dup": 0, "skipped_filter": 0, "skipped_excluded": 0,
             "crawled": 0, "crawl_failed": 0, "errors": []}

    for kw in collect_keywords:
        try:
            items = _call_naver_api(kw.keyword, display, headers, sort=kw.sort)
        except Exception as e:
            stats["errors"].append(f"수집 실패 ({kw.keyword}): {e}")
            continue
        finally:
            if delay > 0:
                time.sleep(delay)

        for item in items:
            title        = _strip_html(item.get("title", ""))
            desc         = _strip_html(item.get("description", ""))
            original_url = item.get("originallink") or ""
            naver_link   = item.get("link") or ""
            url          = original_url or naver_link
            if not url:
                continue

            body = f"{title} {desc}".strip()
            lower_body = body.lower()

            if any(word in lower_body for word in exclude_keywords):
                stats["skipped_filter"] += 1
                continue

            url_hash = _make_url_hash(url)
            existing = News.objects.filter(url_hash=url_hash).first()
            if existing is not None:
                # 같은 기사가 다른 키워드로도 걸린 경우 — 생성 경로는 이미 지나갔지만
                # (앞선 키워드 순회에서 News가 만들어졌으므로) "이 키워드로도 매칭됐다"는
                # 사실 자체는 기존 레코드에 이어 붙인다. 최초 1개만 남기면 복수 매칭 분석을
                # 다시 할 수 없다(2026-08-06 실측: 2개 이상 21건, 4개 이상 4건).
                if kw.keyword not in existing.matched_keywords:
                    existing.matched_keywords = existing.matched_keywords + [kw.keyword]
                    existing.save(update_fields=["matched_keywords"])
                stats["skipped_dup"] += 1
                continue

            if ExcludedURL.objects.filter(url_hash=url_hash).exists():
                stats["skipped_excluded"] += 1
                continue

            published_at = _parse_pub_date(item.get("pubDate", ""))
            if not published_at:
                continue

            news = News.objects.create(
                title=title,
                url=url,
                url_hash=url_hash,
                body=body,
                source_type="naver_news",
                published_at=published_at,
                matched_keywords=[kw.keyword],
            )

            full_body = fetch_article_body(original_url, naver_link)
            if full_body:
                news.body = full_body
                news.save(update_fields=["body"])
                stats["crawled"] += 1
            else:
                stats["crawl_failed"] += 1

            # 태깅 대상 텍스트는 News.body(저장값)와 다르다 — 별칭 매칭 직전에만
            # services/text_cleaning.py의 잔여물 필터를 태워, 매체 템플릿(하단
            # "관련기사" 링크 목록, 시리즈 목차 줄 등)에 걸린 회사명이 태그로
            # 잘못 붙는 걸 막는다(2026-08-05, News pk=751 등에서 실측 확인).
            # 제목(title)은 필터 대상이 아니다 — 잔여물은 본문에서만 발생하고,
            # 제목의 시리즈 목차 접두어("[금융권 인공지능 활용①] ...")는 정당한
            # 매칭 대상이라 잘라내면 안 된다.
            article_content = full_body if full_body else desc
            matching_text = f"{title} {clean_text_for_matching(article_content)}"

            _link_organizations(news, matching_text, orgs)
            _link_tech_topics(news, matching_text, topics)
            stats["collected"] += 1

    return stats


def run_collection(actor: str) -> dict:
    """수집 진입점 단일화 지점(docs/planning.md "수집 파이프라인 관측성 정책" 2번).

    collect_naver()를 부르는 모든 호출부 — SET-001 "지금 수집"(수동), 스케줄러(자동) — 는
    반드시 이 함수를 거쳐야 한다. 호출부에 로그 책임을 맡기면 "경로가 2개인데 하나가 로그를
    빠뜨리는" 실수(collect_now가 CollectionLog를 안 남기던 실제 버그)가 반복되므로, 로그 기록을
    진입점 자체에 묶어 호출부가 몇 개로 늘어도 빠지지 않게 한다. (참고: 기동 시 catch-up(자동
    복구) 경로는 2026-08-04에 도입했다가 같은 날 철회됐다 — 아래 actor 인자의 ACTOR_CATCHUP
    값도 그 흔적으로 남아 있을 뿐 현재 이 값으로 호출하는 코드는 없다.)

    - 반드시 CollectionLog를 1건 남긴다 — 성공이든 collect_naver()가 잡아 stats["errors"]에
      담은 부분 실패든, collect_naver() 자체가 던진 미처리 예외든 전부 여기서 로그로 남긴다.
      "시도가 없었다"와 "시도했으나 실패했다"가 둘 다 "로그 없음"으로 보이던 문제를 없앤다.
    - actor로 실행 주체(자동/수동)를 구분해 기록한다. 수동 실행분이 자동 수집 생존 신호에
      섞이지 않게 하기 위해서다.
    - 예외를 삼키되(호출부는 500 대신 실패 stats를 받는다) 반드시 로그에 남긴 뒤 그렇게 한다 —
      "삼킨다"와 "기록하지 않는다"는 다르다.

    ⚠️ 로그 기록(CollectionLog.objects.create) 자체가 실패해도 이 함수는 예외를 밖으로 던지지
    않는다(실제 사고, 2026-08-04: `actor` 컬럼 마이그레이션이 아직 적용되지 않은 상태에서 코드가
    먼저 반영돼, 수집은 성공했는데 로그 기록에서 psycopg2.UndefinedColumn이 났다. 당시 있었던
    catch-up 경로를 타고 이 예외가 apps.py의 ready()까지 전파돼 개발 서버가 파일을 저장할
    때마다(autoreload 재기동마다) 기동 자체를 실패시켰고, 이 사고를 계기로 catch-up 자체는
    철회됐다). catch-up이 없어진 지금도 이 방어는 유지한다 — 스케줄 잡(_job_collect)이나
    collect_now 뷰가 로그 실패로 죽는 것 자체가 바람직하지 않기 때문이다. 로그 실패는 logger로
    드러내고 stats는 그대로 반환한다 — "기록에 실패했다"를 조용히 삼키진 않되, 그 실패가
    호출부(뷰·스케줄러)를 끌고 내려가게 두지 않는다.
    """
    started_at = timezone.now()
    try:
        stats = collect_naver()
    except Exception as e:
        stats = {"collected": 0, "skipped_dup": 0, "skipped_filter": 0, "skipped_excluded": 0,
                  "crawled": 0, "crawl_failed": 0, "errors": [f"수집 중 처리되지 않은 예외: {e}"]}

    try:
        CollectionLog.objects.create(
            source=None,
            started_at=started_at,
            collected_count=stats["collected"],
            status="fail" if stats["errors"] else "success",
            error_message="\n".join(stats["errors"]) or None,
            actor=actor,
        )
    except Exception:
        logger.exception(
            "CollectionLog 기록 실패 (actor=%s, collected=%s건, 수집 자체는 %s) — "
            "이 수집 시도는 로그에 남지 않았습니다.",
            actor, stats["collected"], "성공" if not stats["errors"] else "실패",
        )
    return stats


def remap_organizations() -> int:
    orgs = list(Organization.objects.filter(is_active=True))
    count = 0
    for news in News.objects.prefetch_related("organizations").all():
        before = set(news.organizations.values_list("pk", flat=True))
        _link_organizations(news, f"{news.title} {clean_text_for_matching(news.body)}", orgs)
        after = set(news.organizations.values_list("pk", flat=True))
        if after != before:
            count += 1
    return count


def remap_tech_topics() -> int:
    topics = list(TechTopic.objects.filter(is_active=True))
    count = 0
    for news in News.objects.prefetch_related("tech_topics").all():
        before = set(news.tech_topics.values_list("pk", flat=True))
        _link_tech_topics(news, f"{news.title} {clean_text_for_matching(news.body)}", topics)
        after = set(news.tech_topics.values_list("pk", flat=True))
        if after != before:
            count += 1
    return count
