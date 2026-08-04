import hashlib
import uuid

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import DeletedNewsRecord, ExcludedURL, News
from .services import delete_news_with_record


def _make_news(**overrides):
    url = f"https://example.com/{uuid.uuid4()}"
    defaults = dict(
        title="테스트 기사",
        url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest(),
        body="본문 테스트",
        source_type="naver_news",
        published_at=timezone.now(),
        status=News.STATUS_VERIFIED,
    )
    defaults.update(overrides)
    return News.objects.create(**defaults)


class DeleteNewsWithRecordTests(TestCase):
    """docs/planning.md "판정 기록 보존 정책"(2026-08-04) — 헬퍼가 기록·차단·삭제를
    한 트랜잭션으로 묶고, 기록 실패 시 삭제 자체를 취소하는지 검증한다."""

    def test_normal_deletion_leaves_record_and_block(self):
        news = _make_news()
        url_hash = news.url_hash
        news_pk = news.pk

        record = delete_news_with_record(
            news, criterion_code="1-b", reason="사유",
            judged_by=DeletedNewsRecord.JUDGED_BY_RA,
        )

        self.assertFalse(News.objects.filter(pk=news_pk).exists())
        self.assertTrue(ExcludedURL.objects.filter(url_hash=url_hash).exists())
        self.assertEqual(record.criterion_code, "1-b")
        self.assertEqual(record.judged_by, DeletedNewsRecord.JUDGED_BY_RA)

    def test_record_failure_aborts_whole_deletion(self):
        news = _make_news()
        url_hash = news.url_hash
        news_pk = news.pk

        orig_create = DeletedNewsRecord.objects.create
        DeletedNewsRecord.objects.create = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            with self.assertRaises(RuntimeError):
                delete_news_with_record(news)
        finally:
            DeletedNewsRecord.objects.create = orig_create

        self.assertTrue(News.objects.filter(pk=news_pk).exists())
        self.assertFalse(ExcludedURL.objects.filter(url_hash=url_hash).exists())
        self.assertFalse(DeletedNewsRecord.objects.filter(url_hash=url_hash).exists())


class NewsDeleteViewTests(TestCase):
    """news_delete 뷰(화면 삭제)도 헬퍼를 거쳐 기록을 남기는지 확인한다."""

    def test_view_delete_creates_user_record(self):
        news = _make_news()
        url_hash = news.url_hash

        response = self.client.post(
            reverse("news_delete", args=[news.uid]), {"source": "list"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(News.objects.filter(url_hash=url_hash).exists())
        self.assertTrue(ExcludedURL.objects.filter(url_hash=url_hash).exists())
        record = DeletedNewsRecord.objects.get(url_hash=url_hash)
        self.assertEqual(record.judged_by, DeletedNewsRecord.JUDGED_BY_USER)
        self.assertEqual(record.criterion_code, "")
        self.assertEqual(record.reason, "")
