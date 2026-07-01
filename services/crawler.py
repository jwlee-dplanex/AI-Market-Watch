import requests
import trafilatura
from bs4 import BeautifulSoup

NAVER_NEWS_DOMAINS = ("news.naver.com", "n.news.naver.com")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}
MIN_BODY_LENGTH = 200
TIMEOUT = 8


def _is_naver_news(url: str) -> bool:
    return any(domain in url for domain in NAVER_NEWS_DOMAINS)


def _fetch_naver_news_body(url: str) -> str | None:
    try:
        res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        area = soup.select_one("#dic_area") or soup.select_one("#articleBodyContents")
        if area:
            for tag in area(["script", "style"]):
                tag.decompose()
            text = area.get_text(separator="\n").strip()
            if len(text) >= MIN_BODY_LENGTH:
                return text
    except Exception:
        pass
    return None


def _fetch_with_trafilatura(url: str) -> str | None:
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(
                downloaded, include_comments=False, include_tables=False
            )
            if text and len(text) >= MIN_BODY_LENGTH:
                return text
    except Exception:
        pass
    return None


def fetch_article_body(original_url: str, naver_link: str = "") -> str | None:
    """
    우선순위:
    1. naver_link가 네이버 뉴스 URL → #dic_area 파싱
    2. original_url → trafilatura
    3. original_url이 네이버 뉴스 URL → #dic_area 파싱
    실패 시 None 반환 (호출자가 기존 snippet 유지)
    """
    if naver_link and _is_naver_news(naver_link):
        body = _fetch_naver_news_body(naver_link)
        if body:
            return body

    if original_url:
        body = _fetch_with_trafilatura(original_url)
        if body:
            return body

    if original_url and _is_naver_news(original_url):
        return _fetch_naver_news_body(original_url)

    return None
