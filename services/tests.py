from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.news.models import News
from apps.setting.models import DataSource, Keyword
from services import collector
from services.dedup_candidates import extract_event_fingerprints

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


# 2026-10-02 신설 — 지문 추출 회귀 방어.
#
# 🔴 이 함수는 틀려도 오류를 내지 않는다. 같은 사건이 뉴스 목록에 여러 건 남는 것이
# 유일한 증상이고, 그것을 사용자가 화면에서 발견했다(삼성화재 피난훈련 3건). 실제
# 제목 셋을 그대로 넣어 그 실패가 다시 생기면 테스트가 깨지게 한다.
#
# ⚠️ 제목은 DB에 있던 값 그대로다(pk=4339·4343·4345). 줄임표와 따옴표를 손대지
# 않는다 — 바로 그 문자들이 종전에 토큰을 한 덩어리로 묶어 매칭을 막았다.
SAMSUNG_TITLES = (
    "삼성화재, AI로 피난훈련 ‘정량평가’…CCTV로 병목구간 찾는다",
    "삼성화재, AI 기반 '피난훈련 정량평가 시스템' 개발…특허 출원 완료",
    "삼성화재, 'AI 기반 피난훈련 정량평가 시스템' 개발…10월 현장 실증",
)


class EventFingerprintTests(SimpleTestCase):
    """services/dedup_candidates.py extract_event_fingerprints()의 불변식."""

    def test_same_event_written_differently_shares_fingerprint(self):
        """같은 사건을 매체마다 다르게 써도 지문이 겹쳐야 한다.

        🔴 이 테스트가 깨지면 중복 기사가 후보 묶음으로 모이지 않아 LLM이 비교할
        기회조차 얻지 못한다. 종전 실패: 세 제목의 교집합이 **0개**였다."""
        fps = [extract_event_fingerprints("", title) for title in SAMSUNG_TITLES]
        for i in range(len(fps)):
            for j in range(i + 1, len(fps)):
                shared = fps[i] & fps[j]
                self.assertTrue(
                    shared, f"제목 {i}와 {j}의 지문 교집합이 비었어요: {SAMSUNG_TITLES[i]!r}",
                )

    def test_punctuation_inside_token_is_split(self):
        """줄임표·따옴표가 가운데 끼여도 어절이 분리돼야 한다.

        종전에는 「정량평가’…CCTV로」가 한 토큰이라 다른 기사의 「정량평가」와 겹칠
        수 없었다(_STRIP_PUNCT_RE는 토큰 양끝만 벗긴다)."""
        fps = extract_event_fingerprints("", SAMSUNG_TITLES[0])
        self.assertIn("피난훈련 정량평가", fps)

    def test_stripping_josa_keeps_the_original_form_too(self):
        """조사를 벗긴 형태와 원형이 둘 다 남아야 한다.

        🔴 _strip_trailing_josa()는 형태소 분석기 없이 글자만 보므로 「정량평가」의
        「가」를 조사로 보고 **「정량평」**으로 깎는다. 「평가」·「증가」·「국가」가 모두
        같은 손상을 입으므로, 어느 쪽이 맞는지 고르지 않고 둘 다 들고 간다."""
        fps = extract_event_fingerprints("", SAMSUNG_TITLES[1])
        self.assertIn("피난훈련 정량평가", fps)
        self.assertIn("피난훈련 정량평", fps)

    def test_ai_bigrams_are_not_fingerprints(self):
        """「AI」가 한쪽에 오는 바이그램은 지문이 아니어야 한다.

        이 서비스의 주제 자체가 「금융권 AI 도입 동향」이라 AI가 붙은 복합어는 어느
        창에서도 흔하다. 실측(최근 7일 창 39건)에서 무관한 기사를 이은 신호가 전부
        이 꼴이었다 — 「AI 에이전트」가 9건, 「인공지능 AI」가 6건, 「금융 AI」가 3건."""
        fps = extract_event_fingerprints("", SAMSUNG_TITLES[1])
        for weak in ("AI 기반", "삼성화재 AI", "인공지능 AI", "금융 AI", "AI 에이전트"):
            self.assertNotIn(weak, fps)

    def test_no_body_and_no_title_gives_empty_set(self):
        """재료가 없으면 빈 집합이다(호출부가 신호 없는 기사를 걸러낼 수 있어야 한다)."""
        self.assertEqual(extract_event_fingerprints("", ""), set())
        self.assertEqual(extract_event_fingerprints(None, None), set())
