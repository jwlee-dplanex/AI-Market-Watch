from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.news.models import News
from apps.setting.models import DataSource, Keyword
from services import collector
from services.dedup_candidates import extract_event_fingerprints
from services.llm import build_short_field, resolve_keep_indices, split_into_sentences

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


# 2026-10-02 신설, 2026-10-06 보강 — 축약본 조립 회귀 방어.
#
# 🔴 이 조립도 틀려도 오류를 내지 않는다. 증상은 화면에서만 보인다 — 이슈가 통째로
# 사라지거나(10-02), 뒤쪽 이슈가 한 문장으로 쪼그라든다(10-06). 둘 다 사용자가 화면에서
# 먼저 발견했다.
SAMPLE_REPORT = """### 첫째 이슈 제목

첫째 문장이다. 둘째 문장이다. 셋째 문장이다. 넷째 문장이다.

참고: uid-aaa

### 둘째 이슈 제목

다섯째 문장이다. 여섯째 문장이다. 일곱째 문장이다. 여덟째 문장이다.

참고: uid-bbb
"""


class BuildShortFieldTests(SimpleTestCase):
    """services/llm.py resolve_keep_indices()/build_short_field()의 불변식."""

    def _first_block_indices(self):
        """첫째 이슈 본문 문장들의 번호. LLM이 그쪽만 골랐다고 흉내 내는 데 쓴다."""
        sentences = split_into_sentences(SAMPLE_REPORT)
        return [
            i for i, s in enumerate(sentences, start=1)
            if "첫째 문장" in s or "둘째 문장" in s
        ]

    def test_issue_heading_survives_even_if_llm_picked_nothing(self):
        """🔴 LLM이 그 블록 문장을 하나도 고르지 않아도 이슈 머리는 남아야 한다.

        종전 실패(Report 27): 머리와 본문이 빠지고 `참고:` 줄만 세 개 연달아 남아,
        화면에서 뒤쪽 두 이슈가 사라져 보였다."""
        short = build_short_field(
            SAMPLE_REPORT, self._first_block_indices(),
            always_keep_prefix="참고:", block_prefix="###",
        )
        self.assertEqual(short.count("###"), 2)
        self.assertIn("### 둘째 이슈 제목", short)

    def test_block_without_picks_gets_three_sentences(self):
        """🔴 번호가 없는 블록에는 앞 세 문장이 들어가야 한다.

        종전에는 첫 문장 하나만 넣어서, 10월 1주차 보고서의 4번과 5번 이슈가 76자와
        166자(긴 버전의 13%·20%)로 남았다. 세 문장인 근거는 같은 보고서에서 LLM이
        직접 고른 블록 가운데 가장 짧은 것이 3문장이었다는 실측이다."""
        short = build_short_field(
            SAMPLE_REPORT, self._first_block_indices(),
            always_keep_prefix="참고:", block_prefix="###",
        )
        self.assertIn("다섯째 문장", short)
        self.assertIn("여섯째 문장", short)
        self.assertIn("일곱째 문장", short)
        # 네 번째는 넣지 않는다 — 축약이기 때문이다.
        self.assertNotIn("여덟째 문장", short)

    def test_reference_line_starts_its_own_line(self):
        """🔴 `참고:` 줄은 줄머리에 와야 한다.

        본문 문장과 한 줄에 붙으면 report_issues()가 그 줄을 본문으로 읽어 근거
        기사를 하나도 못 찾는다(실측: 근거가 빈 배열로 나오고 화면에 「참고:」가
        그대로 찍혔다)."""
        short = build_short_field(
            SAMPLE_REPORT, self._first_block_indices(),
            always_keep_prefix="참고:", block_prefix="###",
        )
        self.assertEqual(short.count("참고:"), 2)
        for line in short.split("\n"):
            if "참고:" in line:
                self.assertTrue(
                    line.lstrip().startswith("참고:"),
                    f"`참고:` 가 줄머리에 없어요: {line!r}",
                )

    def test_short_field_uses_only_original_sentences(self):
        """🔴 축약본은 원문 문장만 이어 붙인다(빼는 것만 허용)."""
        short = build_short_field(
            SAMPLE_REPORT, self._first_block_indices(),
            always_keep_prefix="참고:", block_prefix="###",
        )
        sentences = split_into_sentences(SAMPLE_REPORT)
        indices = resolve_keep_indices(
            SAMPLE_REPORT, self._first_block_indices(),
            always_keep_prefix="참고:", block_prefix="###",
        )
        self.assertEqual("".join(sentences[i - 1] for i in indices), short)
        for i in indices:
            self.assertIn(sentences[i - 1], SAMPLE_REPORT)

    def test_split_into_sentences_round_trips(self):
        """🔴 `"".join(split_into_sentences(t)) == t` — 축약본 설계 전체가 이 불변식
        하나에 기대고 있다."""
        for text in (SAMPLE_REPORT, "", "한 문장이다.", "줄바꿈\n있는 글이다."):
            self.assertEqual("".join(split_into_sentences(text)), text)
