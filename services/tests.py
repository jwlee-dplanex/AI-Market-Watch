from unittest.mock import patch

from django.test import TestCase

from apps.news.models import News
from apps.setting.models import DataSource, Keyword
from services import collector

PUB_DATE = "Thu, 06 Aug 2026 09:00:00 +0900"


def _item(slug: str) -> dict:
    url = f"https://example.com/{slug}"
    return {
        "title": f"테스트기사 {slug}",
        "description": "설명",
        "originallink": url,
        "link": url,
        "pubDate": PUB_DATE,
    }


class CollectNaverMatchedKeywordsTests(TestCase):
    """2026-08-06 도입(PM P1) — 수집 루프 구조상 두 번째 키워드가 이미 존재하는
    News를 가져오면(url_hash 중복) 그 시점엔 생성 경로를 타지 않는다. 그래도
    "이 키워드로도 매칭됐다"는 사실은 기존 레코드에 이어 붙여야 한다는 요구사항의
    회귀 테스트. `docs/planning.md`가 아니라 이번 PM 요청(2026-08-06)에 근거."""

    def setUp(self):
        DataSource.objects.create(name="Naver News API", is_active=True)
        self.kw1 = Keyword.objects.create(
            keyword="검증용키워드1", keyword_type=Keyword.TYPE_COLLECT, is_active=True,
        )
        self.kw2 = Keyword.objects.create(
            keyword="검증용키워드2", keyword_type=Keyword.TYPE_COLLECT, is_active=True,
        )

    def _fake_call_naver_api(self, query, display, headers, sort="date"):
        if query == "검증용키워드1":
            return [_item("shared-article")]
        if query == "검증용키워드2":
            return [_item("shared-article"), _item("only-kw2-article")]
        return []

    def test_article_matched_by_multiple_keywords_records_all(self):
        with patch.object(collector, "_call_naver_api", side_effect=self._fake_call_naver_api), \
             patch.object(collector, "fetch_article_body", return_value=None):
            stats = collector.collect_naver()

        shared = News.objects.get(
            url_hash=collector._make_url_hash("https://example.com/shared-article")
        )
        only_kw2 = News.objects.get(
            url_hash=collector._make_url_hash("https://example.com/only-kw2-article")
        )

        self.assertEqual(shared.matched_keywords, ["검증용키워드1", "검증용키워드2"])
        self.assertEqual(only_kw2.matched_keywords, ["검증용키워드2"])
        self.assertEqual(stats["collected"], 2)
        self.assertEqual(stats["skipped_dup"], 1)

    def test_same_keyword_matching_twice_does_not_duplicate(self):
        """같은 키워드가 같은 기사를 다시 물어도(방어적 케이스) matched_keywords에
        중복으로 쌓이지 않아야 한다."""
        def fake(query, display, headers, sort="date"):
            return [_item("shared-article")]

        with patch.object(collector, "_call_naver_api", side_effect=fake), \
             patch.object(collector, "fetch_article_body", return_value=None):
            collector.collect_naver()
            collector.collect_naver()

        shared = News.objects.get(
            url_hash=collector._make_url_hash("https://example.com/shared-article")
        )
        self.assertEqual(shared.matched_keywords, ["검증용키워드1", "검증용키워드2"])
