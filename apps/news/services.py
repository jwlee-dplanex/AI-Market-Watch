"""안전 삭제 헬퍼 — docs/planning.md "판정 기록 보존 정책: 버린 것도 자산이다" (2026-08-04 확정).

뉴스 삭제는 항상 이 모듈의 `delete_news_with_record()`를 거친다. RA·화면(`news_delete`
뷰) 어느 경로든 예외 없이 여기를 통과해야 "기록 없는 삭제 경로 0개"가 성립한다.

절차(한 트랜잭션): ① DeletedNewsRecord 생성 → ② ExcludedURL.get_or_create → ③ news.delete()
①이 실패하면 ②·③도 실행되지 않고 삭제 자체가 취소된다 — 근거를 남기지 못할 바에는
삭제를 미루는 쪽이 안전하다(그 뉴스는 아직 미검증이라 검증 게이트가 화면 노출을 막아준다).
"""

from django.db import transaction

from .models import DeletedNewsRecord, ExcludedURL, News


def delete_news_with_record(
    news: News,
    *,
    criterion_code: str = "",
    reason: str = "",
    judged_by: str = DeletedNewsRecord.JUDGED_BY_RA,
) -> DeletedNewsRecord:
    """뉴스 한 건을 판정 기록을 남기며 안전하게 삭제한다.

    RA가 배치를 처리할 때 이 함수 하나만 호출하면 된다 — 기록 생성·재수집 차단·삭제
    3단계를 손으로 조합하지 않는 것이 이 헬퍼의 핵심 목적이다(3단계를 매번 손으로
    조합하다 보면 바쁜 배치에서 한 단계가 조용히 빠지고, 그게 786건이 생긴 방식이다).

    여러 건을 삭제할 때도 이 함수를 건별로 개별 호출한다 — News.objects.filter(...).delete()
    같은 일괄 삭제는 절대 쓰지 않는다(ExcludedURL 기록이 안 남아 재수집을 막지 못한다).

    사용 예시 (RA 배치 처리):
        from apps.news.models import News, DeletedNewsRecord
        from apps.news.services import delete_news_with_record

        news = News.objects.get(uid=some_uid)
        delete_news_with_record(
            news,
            criterion_code="1-b",
            reason="AI는 부차 요소로만 곁들여지고 지배적 주제는 실적 발표.",
            judged_by=DeletedNewsRecord.JUDGED_BY_RA,
        )

    사용 예시 (화면 삭제 경로, apps/news/views.py: news_delete):
        delete_news_with_record(news, judged_by=DeletedNewsRecord.JUDGED_BY_USER)
        # 기준 코드·사유는 빈 값 허용 — 사유 입력 UI를 별도로 만들지 않는다(정책 3번).

    Args:
        news: 삭제할 News 인스턴스.
        criterion_code: 적용 판정 기준 코드(권장 어휘, 자유 문자열). 빈 값 허용.
        reason: 삭제 사유 1~2문장 자유 서술. 빈 값 허용.
        judged_by: 판정 주체. 기본값은 RA(RA가 배치 처리 중 호출하는 게 주 사용처이므로).
            화면 삭제 경로는 반드시 DeletedNewsRecord.JUDGED_BY_USER를 명시해야 한다.

    Returns:
        생성된 DeletedNewsRecord.

    Raises:
        판정 기록(①) 생성이 실패하면 그 예외가 그대로 전파되고, 트랜잭션 전체가 롤백돼
        ExcludedURL도 news.delete()도 실행되지 않는다 — 해당 News는 삭제되지 않고 남는다.
    """
    with transaction.atomic():
        # ① 판정 기록 생성 — 실패하면 아래 ②·③도 실행되지 않는다(트랜잭션 롤백).
        record = DeletedNewsRecord.objects.create(
            title=news.title,
            url=news.url,
            url_hash=news.url_hash,
            body=news.body,
            source_type=news.source_type,
            published_at=news.published_at,
            collected_at=news.collected_at,
            criterion_code=criterion_code,
            reason=reason,
            judged_by=judged_by,
            organizations_snapshot=list(
                news.organizations.order_by("name").values_list("name", flat=True)
            ),
            tech_topics_snapshot=list(
                news.tech_topics.order_by("name").values_list("name", flat=True)
            ),
        )

        # ② 재수집 차단 인덱스 — 기존 RA 안전 삭제 패턴과 동일, 어떤 경우에도 건너뛰지 않는다.
        ExcludedURL.objects.get_or_create(url_hash=news.url_hash)

        # ③ 실제 삭제
        news.delete()

    return record
