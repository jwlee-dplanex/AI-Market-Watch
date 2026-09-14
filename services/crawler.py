import re

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
# 실체 축 관문(docs/planning.md 뉴스룸 정책 6-3절). "완결된 서술문"이 한 문장이라도
# 있으려면 최소 이 정도 길이의 절이 마침표 앞에 있어야 한다는 보수적인 하한이다.
MIN_SENTENCE_CLAUSE_LENGTH = 10
TIMEOUT = 8


def has_complete_sentence(text: str) -> bool:
    """문자열 안에 마침표로 끝나는 완결된 서술문이 하나라도 있으면 True.

    뉴스룸 정책 6-3 "본문이 사실상 없는 기사" 절의 실체 축 판별 기준이다. 매체별
    추출 규칙이나 도메인은 보지 않고 문장 구조만 본다 — 숫자 뒤의 마침표(날짜
    "2026.09.14", 백분율 "200.4%", 소수점 등)는 문장 종결로 보지 않고, 마침표
    직전까지의 절이 일정 길이 이상이며 한글을 포함해야 문장으로 인정한다.

    실측(2026-09-14, NewsroomArticle 245건 전수)으로 이 기준이 이데일리 메뉴 덤프
    9건(등록 시각·기자명·코너명이 줄바꿈으로 나열될 뿐 마침표로 끝나는 문장이 하나도
    없음)만 정확히 걸러내고, 훨씬 짧은 더벨 절단 기사(예: "인수합병(M&A) 절차가
    본격화됐다.")는 통과시키는 것을 확인했다. 「적으면」이 아니라 「하나도 없으면」이라
    보수적으로 잡는다 — 잘못 버리는 비용이 더 크다.
    """
    if not text:
        return False
    last_boundary = 0
    for i, ch in enumerate(text):
        if ch == ".":
            prev_char = text[i - 1] if i > 0 else ""
            if prev_char.isdigit():
                continue
            clause = text[last_boundary:i].strip()
            if len(clause) >= MIN_SENTENCE_CLAUSE_LENGTH and re.search(r"[가-힣]", clause):
                return True
            last_boundary = i + 1
        elif ch == "\n":
            last_boundary = i + 1
    return False


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
            if len(text) >= MIN_BODY_LENGTH and has_complete_sentence(text):
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
            if text and len(text) >= MIN_BODY_LENGTH and has_complete_sentence(text):
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
