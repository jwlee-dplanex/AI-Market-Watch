"""판정 기록 보존 헬퍼 — docs/planning.md "판정 기록 보존 정책: 버린 것도 자산이다" (2026-08-04 확정).

두 안전 헬퍼를 제공한다. RA·화면 어느 경로든 예외 없이 이 헬퍼들을 통과해야 "기록
없는 판정 경로 0개"가 성립한다.

- `delete_news_with_record()` (P0) — 뉴스 삭제. 절차(한 트랜잭션):
  ① DeletedNewsRecord 생성 → ② ExcludedURL.get_or_create → ③ news.delete()
  ①이 실패하면 ②·③도 실행되지 않고 삭제 자체가 취소된다 — 근거를 남기지 못할 바에는
  삭제를 미루는 쪽이 안전하다(그 뉴스는 아직 미검증이라 검증 게이트가 화면 노출을 막아준다).

- `correct_news_tag()` (P1) — 살아남는 뉴스의 기업/기술 주제 태그 교정(추가·제거).
  삭제와 달리 뉴스 자체는 남으므로 ExcludedURL·본문 스냅샷은 필요 없고, TagCorrectionRecord
  생성과 M2M 변경만 한 트랜잭션으로 묶는다.
"""

from django.db import transaction

from .models import DeletedNewsRecord, ExcludedURL, News, TagCorrectionRecord


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
            matched_keywords_snapshot=list(news.matched_keywords),
        )

        # ② 재수집 차단 인덱스 — 기존 RA 안전 삭제 패턴과 동일, 어떤 경우에도 건너뛰지 않는다.
        ExcludedURL.objects.get_or_create(url_hash=news.url_hash)

        # ③ 실제 삭제
        news.delete()

    return record


def correct_news_tag(
    news: News,
    target,
    *,
    action: str,
    reason: str = "",
    judged_by: str = TagCorrectionRecord.JUDGED_BY_RA,
) -> TagCorrectionRecord:
    """뉴스 한 건의 기업/기술 주제 태그를 추가·제거하면서 교정 이력을 함께 남긴다.

    docs/planning.md "판정 기록 보존 정책" 4번(P1). `news.organizations.add(org)` /
    `news.organizations.remove(org)`를 직접 호출하는 대신 이 함수를 쓴다 — 한 번 호출로
    "떼면서/붙이면서 기록"이 된다. 이 정책이 P0(`delete_news_with_record`)과 별개인
    이유: 대상 뉴스는 삭제되지 않고 살아남으므로, `ExcludedURL` 재수집 차단이나 판정
    기록의 "본문 스냅샷"은 필요 없다 — 사라지는 건 "뗀/붙인 태그"라는 차분뿐이다.

    축(기업 vs 기술 주제)은 `target`의 타입으로 자동 판별한다(`Organization` 인스턴스면
    "기업", `TechTopic` 인스턴스면 "기술 주제") — 호출부가 축을 문자열로 따로 넘기다
    오타를 낼 여지를 없앤다.

    사용 예시 (RA 배치 처리, 배경 언급이라 태그 제거):
        from apps.setting.models import Organization
        from apps.news.models import TagCorrectionRecord
        from apps.news.services import correct_news_tag

        org = Organization.objects.get(name="신한은행")
        correct_news_tag(
            news, org,
            action=TagCorrectionRecord.ACTION_REMOVE,
            reason="한편... 경쟁사 비교 문단, 핵심 주체 아님",
        )

    사용 예시 (핵심 주체인데 누락돼 있어 태그 추가):
        correct_news_tag(
            news, org,
            action=TagCorrectionRecord.ACTION_ADD,
            reason="본문 전체가 이 기업의 자체 LLM 구축 사례",
        )

    Args:
        news: 대상 News (삭제되지 않고 살아남는 뉴스).
        target: `Organization` 또는 `TechTopic` 인스턴스.
        action: `TagCorrectionRecord.ACTION_ADD` / `ACTION_REMOVE`.
        reason: 교정 사유, 짧게(1문장 권장). 빈 값을 허용하지만 채우는 걸 강력히 권장한다
            — 사유가 없으면 이 정책의 목적(옵션 B 판별 로직 명세)이 달성되지 않는다.
        judged_by: 판정 주체. 기본값은 RA.

    Returns:
        생성된 TagCorrectionRecord.

    Raises:
        TypeError: target이 Organization도 TechTopic도 아닌 경우.
        ValueError: action이 add/remove가 아닌 경우.
    """
    from apps.setting.models import Organization, TechTopic

    if isinstance(target, Organization):
        axis = TagCorrectionRecord.AXIS_ORGANIZATION
        manager = news.organizations
    elif isinstance(target, TechTopic):
        axis = TagCorrectionRecord.AXIS_TECH_TOPIC
        manager = news.tech_topics
    else:
        raise TypeError(f"target은 Organization 또는 TechTopic이어야 합니다: {type(target)!r}")

    if action not in (TagCorrectionRecord.ACTION_ADD, TagCorrectionRecord.ACTION_REMOVE):
        raise ValueError(f"action은 add/remove여야 합니다: {action!r}")

    with transaction.atomic():
        if action == TagCorrectionRecord.ACTION_ADD:
            manager.add(target)
        else:
            manager.remove(target)

        record = TagCorrectionRecord.objects.create(
            news=news,
            axis=axis,
            action=action,
            target_name=target.name,
            reason=reason,
            judged_by=judged_by,
        )

    return record
