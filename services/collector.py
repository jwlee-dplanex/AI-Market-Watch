import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime

from django.conf import settings

from apps.news.models import News
from apps.setting.models import Keyword, Organization

NAVER_ENDPOINT = "https://openapi.naver.com/v1/search/news.json"


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _make_url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def _parse_pub_date(pub_date_str: str):
    try:
        return parsedate_to_datetime(pub_date_str)
    except Exception:
        return None


def _call_naver_api(query: str, display: int, headers: dict) -> list:
    params = urllib.parse.urlencode({
        "query": query,
        "display": display,
        "start": 1,
        "sort": "date",
    })
    req = urllib.request.Request(f"{NAVER_ENDPOINT}?{params}", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode("utf-8")).get("items", [])


def _link_organizations(news: News, text: str, orgs: list[Organization]) -> None:
    lower_text = text.lower()
    for org in orgs:
        all_names = [org.name] + list(org.aliases or [])
        if any(alias and alias.lower() in lower_text for alias in all_names):
            news.organizations.add(org)


def collect_naver() -> dict:
    if not settings.NAVER_CLIENT_ID or not settings.NAVER_CLIENT_SECRET:
        return {"collected": 0, "skipped_dup": 0, "skipped_filter": 0, "errors": ["Naver API key not configured"]}

    headers = {
        "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
        "User-Agent": "AI-Market-Watch/1.0",
    }
    display     = settings.NAVER_DISPLAY_PER_QUERY
    max_per_org = settings.NAVER_MAX_PER_ORG
    delay       = settings.NAVER_REQUEST_DELAY

    orgs             = list(Organization.objects.filter(is_active=True))
    collect_keywords = list(Keyword.objects.filter(keyword_type=Keyword.TYPE_COLLECT, is_active=True))
    exclude_keywords = [kw.keyword.lower() for kw in Keyword.objects.filter(keyword_type=Keyword.TYPE_EXCLUDE, is_active=True)]
    context_keywords = list(Keyword.objects.filter(keyword_type=Keyword.TYPE_CONTEXT, is_active=True))

    stats = {"collected": 0, "skipped_dup": 0, "skipped_filter": 0, "errors": []}

    # Track A — 기업 × 수집키워드 조합 검색
    for org in orgs:
        accepted = 0
        all_names = [org.name] + list(org.aliases or [])

        for kw in collect_keywords:
            if accepted >= max_per_org:
                break
            query = f"{org.name} {kw.keyword}"
            try:
                items = _call_naver_api(query, display, headers)
            except Exception as e:
                stats["errors"].append(f"Track A 실패 ({query}): {e}")
                continue
            finally:
                if delay > 0:
                    time.sleep(delay)

            for item in items:
                if accepted >= max_per_org:
                    break
                title  = _strip_html(item.get("title", ""))
                desc   = _strip_html(item.get("description", ""))
                url    = item.get("originallink") or item.get("link") or ""
                if not url:
                    continue

                body = f"{title} {desc}".strip()
                lower_body = body.lower()

                # 기관 alias 매칭
                if not any(alias and alias.lower() in lower_body for alias in all_names):
                    stats["skipped_filter"] += 1
                    continue

                # 제외 키워드 필터
                if any(word in lower_body for word in exclude_keywords):
                    stats["skipped_filter"] += 1
                    continue

                url_hash = _make_url_hash(url)
                if News.objects.filter(url_hash=url_hash).exists():
                    stats["skipped_dup"] += 1
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
                    is_processed=False,
                )
                news.organizations.add(org)
                accepted += 1
                stats["collected"] += 1

    # Track B — 컨텍스트 단독 쿼리 검색
    for kw in context_keywords:
        query = kw.keyword
        try:
            items = _call_naver_api(query, display, headers)
        except Exception as e:
            stats["errors"].append(f"Track B 실패 ({query}): {e}")
            continue
        finally:
            if delay > 0:
                time.sleep(delay)

        for item in items:
            title  = _strip_html(item.get("title", ""))
            desc   = _strip_html(item.get("description", ""))
            url    = item.get("originallink") or item.get("link") or ""
            if not url:
                continue

            body = f"{title} {desc}".strip()
            lower_body = body.lower()

            # 제외 키워드 필터
            if any(word in lower_body for word in exclude_keywords):
                stats["skipped_filter"] += 1
                continue

            url_hash = _make_url_hash(url)
            if News.objects.filter(url_hash=url_hash).exists():
                stats["skipped_dup"] += 1
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
                is_processed=False,
            )
            _link_organizations(news, body, orgs)
            stats["collected"] += 1

    return stats
