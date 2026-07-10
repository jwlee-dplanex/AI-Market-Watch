import hashlib
import html
import json
import re
import time
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime

from django.conf import settings

from apps.news.models import ExcludedURL, News
from apps.setting.models import DataSource, Keyword, Organization, TechTopic
from services.crawler import fetch_article_body

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
    """
    if not alias:
        return False
    needle = alias.lower()
    if not needle:
        return False
    start = 0
    text_len = len(lower_text)
    needle_len = len(needle)
    while True:
        idx = lower_text.find(needle, start)
        if idx == -1:
            return False
        before_ok = idx == 0 or not _is_word_char(lower_text[idx - 1])
        after_idx = idx + needle_len
        after_ok = after_idx == text_len or not _is_word_char(lower_text[after_idx])
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
            if News.objects.filter(url_hash=url_hash).exists():
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
            )

            full_body = fetch_article_body(original_url, naver_link)
            if full_body:
                news.body = full_body
                news.save(update_fields=["body"])
                stats["crawled"] += 1
            else:
                stats["crawl_failed"] += 1

            _link_organizations(news, full_body or body, orgs)
            _link_tech_topics(news, full_body or body, topics)
            stats["collected"] += 1

    return stats


def remap_organizations() -> int:
    orgs = list(Organization.objects.filter(is_active=True))
    count = 0
    for news in News.objects.prefetch_related("organizations").all():
        before = set(news.organizations.values_list("pk", flat=True))
        _link_organizations(news, f"{news.title} {news.body}", orgs)
        after = set(news.organizations.values_list("pk", flat=True))
        if after != before:
            count += 1
    return count


def remap_tech_topics() -> int:
    topics = list(TechTopic.objects.filter(is_active=True))
    count = 0
    for news in News.objects.prefetch_related("tech_topics").all():
        before = set(news.tech_topics.values_list("pk", flat=True))
        _link_tech_topics(news, f"{news.title} {news.body}", topics)
        after = set(news.tech_topics.values_list("pk", flat=True))
        if after != before:
            count += 1
    return count
