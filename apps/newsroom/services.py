import time
from datetime import timedelta
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.utils import timezone

from services.collector import _call_naver_api, _make_url_hash, _parse_pub_date, _strip_html
from services.crawler import fetch_article_body

from .models import NewsroomArticle, PaidDomain

# --- 코드 필터 3종 (docs/planning.md 뉴스룸 정책 6번 표: 10-2 유료 구독 · 10-3 기간
# 불일치 · 10-4 죽은 링크. 파이프라인 순서는 8번 표 "1 수집 → 2 본문 크롤 → 3 코드
# 필터 → 4 1단계 LLM"이지만, 이 구현은 코드 필터를 본문 크롤보다 먼저 돈다 — 어차피
# 버릴 기사에 트래필라투라 본문 추출까지 태우면 낭비이기 때문이다. 결과(필터링되면
# 저장하지 않는다)는 동일하다. ---

# 10-3 기간 불일치. planning.md가 정확한 일수를 못박지 않아 PE가 정한 기본값이다 —
# 매일 브리핑 채널이라도 사람이 며칠 수집을 건너뛸 수 있어(로컬은 수동 실행) 너무
# 좁게 잡으면(예: 7일) 여전히 유효한 기사가 잘려나가고, 너무 넓으면 필터 효과가
# 없다. 중간값으로 과거 30일을 기본으로 두고 운영 중 조정이 필요하면 이 상수만 고친다.
PERIOD_MISMATCH_PAST_DAYS = 30
# 미래 날짜는 파싱 오류·시계 어긋남 정도만 있어도 발생하므로 여유를 하루만 둔다.
PERIOD_MISMATCH_FUTURE_DAYS = 1

# 10-4 죽은 링크. 정책 9번 결정 ④ — "불확실하면 포함한다. dead로 확정된 것만 제외."
# 언론사 서버가 봇 트래픽에 403을 흔히 주므로 403은 여기 넣지 않는다(불확실 취급).
DEAD_LINK_STATUS_CODES = {404, 410}
DEAD_LINK_TIMEOUT = 5
_DEAD_LINK_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}


def _domain_of(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        return netloc[4:] if netloc.startswith("www.") else netloc
    except ValueError:
        return ""


def _is_period_mismatch(published_at) -> bool:
    now = timezone.now()
    if published_at > now + timedelta(days=PERIOD_MISMATCH_FUTURE_DAYS):
        return True
    return published_at < now - timedelta(days=PERIOD_MISMATCH_PAST_DAYS)


def _is_paid_domain(url: str, paid_domains: set) -> bool:
    return _domain_of(url) in paid_domains


def _is_dead_link(url: str) -> bool:
    """확정된 죽은 링크(404/410)만 True. 타임아웃·연결 실패·403 등 불확실한 경우는
    전부 False(포함) — 정책 9번 결정 ④를 그대로 따른다. HEAD로 충분히 가볍게 확인한다
    (일부 서버가 HEAD에 405를 주더라도 405는 DEAD_LINK_STATUS_CODES에 없어 포함으로
    처리되므로 별도 GET 재시도는 하지 않는다 — 확정 판정에만 관심이 있다)."""
    try:
        res = requests.head(url, headers=_DEAD_LINK_HEADERS, timeout=DEAD_LINK_TIMEOUT, allow_redirects=True)
        return res.status_code in DEAD_LINK_STATUS_CODES
    except Exception:
        return False


def collect_newsroom(newsroom) -> dict:
    """뉴스룸 전용 수집 파이프라인(docs/planning.md 뉴스룸 정책 3·4번 + 6번 표 코드 필터).

    본 수집 파이프라인(services/collector.py의 collect_naver())과 완전히 분리된 경로다 —
    별도 키워드 테이블(NewsroomKeyword), 별도 저장 테이블(NewsroomArticle)을 쓰고 조직·
    기술 주제 태깅도 하지 않는다(뉴스룸은 기업 태깅을 하지 않는다, 정책 1번 표).

    ⚠️ collector.py 본체는 고치지 않는다 — 순수 헬퍼(_call_naver_api·_strip_html·
    _make_url_hash·_parse_pub_date)만 import해서 재사용한다(정책 4번 표. 공용 모듈로
    옮기는 리팩터링은 본 파이프라인 회귀 위험이 커서 하지 않는다). services/crawler.py의
    fetch_article_body()도 손대지 않고 호출만 한다.

    🔴 코드 필터(기간 불일치·유료 매체·죽은 링크)에 걸린 기사는 **저장하지 않는다.**
    `filter_status`/`judged_by`를 미리 채우는 방식(대안 B)은 기각됐다
    (docs/planning.md 3745·3732행 — filter_status를 코드 필터가 미리 채우면 5-1 예외가
    첫날부터 닫혀 목적을 잃는다). collect_naver()의 제외 키워드 필터와 동일한 방식으로
    행 자체를 만들지 않고 stats 카운트만 남긴다 — 애초에 테이블에 없는 행이므로
    NewsroomArticleQuerySet.judged()에 절대 영향을 주지 않는다.

    ExcludedURL을 확인하지 않는다 — 그건 RA 삭제분 재수집 차단용이고, 뉴스룸은 사람
    삭제 기능 자체가 없다(정책 9번 결정 ⑧). 유일성은 (newsroom, url_hash) 복합 unique로
    충분하다. DataSource("Naver News API") 활성 여부도 확인하지 않는다 — 그 테이블은
    본 파이프라인 전용으로 남기기로 확정됐다(정책 4번 표 "재사용 안 함").

    반환 dict는 SET-001 `_collect_result.html`과 같은 키 형태를 그대로 쓴다(SET-009
    "지금 수집" 결과가 그 템플릿을 그대로 재사용하기 위함). skipped_excluded는 이
    경로에 존재하지 않는 개념이라 항상 0으로 채운다. skipped_period/skipped_paid/
    skipped_dead는 이번 코드 필터 3종 전용 카운트다.
    """
    if not settings.NAVER_CLIENT_ID or not settings.NAVER_CLIENT_SECRET:
        return {"collected": 0, "skipped_dup": 0, "skipped_filter": 0, "skipped_excluded": 0,
                "skipped_period": 0, "skipped_paid": 0, "skipped_dead": 0,
                "crawled": 0, "crawl_failed": 0, "errors": ["Naver API key not configured"]}

    headers = {
        "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
        "User-Agent": "AI-Market-Watch/1.0",
    }
    delay = settings.NAVER_REQUEST_DELAY

    keywords = list(newsroom.keywords.all())
    paid_domains = set(PaidDomain.objects.values_list("domain", flat=True))
    stats = {"collected": 0, "skipped_dup": 0, "skipped_filter": 0, "skipped_excluded": 0,
              "skipped_period": 0, "skipped_paid": 0, "skipped_dead": 0,
              "crawled": 0, "crawl_failed": 0, "errors": []}

    if not keywords:
        stats["errors"].append("등록된 키워드가 없어요.")
        return stats

    for kw in keywords:
        try:
            items = _call_naver_api(kw.keyword, kw.display, headers, sort=kw.sort)
        except Exception as e:
            stats["errors"].append(f"수집 실패 ({kw.keyword}): {e}")
            continue
        finally:
            if delay > 0:
                time.sleep(delay)

        for item in items:
            title = _strip_html(item.get("title", ""))
            desc = _strip_html(item.get("description", ""))
            original_url = item.get("originallink") or ""
            naver_link = item.get("link") or ""
            url = original_url or naver_link
            if not url:
                continue

            url_hash = _make_url_hash(url)
            if NewsroomArticle.objects.filter(newsroom=newsroom, url_hash=url_hash).exists():
                stats["skipped_dup"] += 1
                continue

            published_at = _parse_pub_date(item.get("pubDate", ""))
            if not published_at:
                continue

            if _is_period_mismatch(published_at):
                stats["skipped_period"] += 1
                continue
            if _is_paid_domain(url, paid_domains):
                stats["skipped_paid"] += 1
                continue
            if _is_dead_link(url):
                stats["skipped_dead"] += 1
                continue

            article = NewsroomArticle.objects.create(
                newsroom=newsroom,
                title=title,
                url=url,
                url_hash=url_hash,
                body=desc,
                published_at=published_at,
            )

            full_body = fetch_article_body(original_url, naver_link)
            if full_body:
                article.body = full_body
                article.save(update_fields=["body"])
                stats["crawled"] += 1
            else:
                stats["crawl_failed"] += 1

            stats["collected"] += 1

    return stats
