import uuid
from urllib.parse import urlparse

from django.db import models
from django.utils import timezone


class Newsroom(models.Model):
    """뉴스룸(브리핑 채널) 하나 = 카드 하나 = 채널 하나(docs/planning.md "뉴스룸: 그룹 단위
    뉴스 브리핑 채널" 1번). 수집 키워드·필터 프롬프트·발송문 프롬프트·Slack 채널·발송
    시각이 이 레코드 하나 안에서 완결된다.

    🔴 기존 리서치 축 자산(News/Keyword/SlackConfig/CollectionLog/Prompt)을 재사용하지
    않는다 — 위 정책 문서 4번 표의 근거 그대로: DataSource·SlackConfig는 단일 레코드
    전제라 카드마다 다른 값을 가질 수 없고, CollectionLog에 섞이면 자동 수집 생존 신호가
    오염된다.

    ⚠️ 1단계에는 LLM·발송 실행이 붙지 않는다(SET-009 "지금 수집"만 동작). 그래도
    filter_prompt/compose_prompt와 발송 섹션 필드는 지금 폼에 자리를 잡는다 — 2~4단계에
    폼 구조를 다시 짜지 않기 위해서다(docs/design.md SET-009 절).
    """

    FREQ_WEEKDAY = "weekday"
    FREQ_DAILY = "daily"
    FREQ_CHOICES = [
        (FREQ_WEEKDAY, "평일 (월~금)"),
        (FREQ_DAILY, "매일"),
    ]

    # URL에 순번 pk를 그대로 노출하지 않는다 — News.uid/Report.uid와 동일 패턴
    # (config/converters.py ShortUUIDConverter, 2026-09-02 추가).
    uid = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    # 선별·작성 프롬프트 (2단계에서 실제로 호출된다. 1단계는 입력·저장만 가능)
    filter_prompt = models.TextField(blank=True)
    compose_prompt = models.TextField(blank=True)

    # 발송 설정 (4단계에서 실제로 발송된다. 1단계는 입력·저장만 가능)
    slack_channel_name = models.CharField(max_length=100, blank=True)
    slack_webhook_url = models.URLField(max_length=2000, blank=True)
    send_hour = models.PositiveSmallIntegerField(default=8)
    send_minute = models.PositiveSmallIntegerField(default=0)
    send_frequency = models.CharField(max_length=10, choices=FREQ_CHOICES, default=FREQ_WEEKDAY)
    send_is_active = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # ROOM-001 정렬(docs/design.md): 활성 먼저, 그 안에서 이름 오름차순.
        ordering = ["-is_active", "name"]

    def __str__(self):
        return self.name

    @property
    def article_count(self):
        """ROOM-001 카드에 쓰는 "기사" 지표(2026-09-02, PD 요청 — "오늘 수집" 대신
        총 건수 하나만). ROOM-002가 실제로 보여주는 건수와 반드시 같아야 하므로(카드
        숫자와 상세 화면 숫자가 다르면 더 나쁘다는 지적) `for_newsroom_display()`를
        그대로 재사용한다 — 노출 게이트를 우회해 `self.articles.count()`처럼 직접
        세면 안 된다(5-1 예외 적용 전/후 다른 숫자가 나올 수 있음).

        ⚠️ `today_metric`은 지우지 않는다 — 5-1 예외에 맞춰 라벨이 스스로 전환되는
        구조는 PM 요건(카드 지표 라벨 "오늘 수집"→"오늘 통과")이라 나중에 다른 자리
        (예: SET-009 요약)에서 쓸 수 있다. 이 프로퍼티는 그것과 별개로 카드 전용이다."""
        return NewsroomArticle.objects.for_newsroom_display(self).count()

    @property
    def has_filter_history(self):
        """5-1 예외("판정 도입 전 예외")가 닫혔는지 여부 — 이 뉴스룸에 filter_status가
        pending이 아닌 기사가 한 건이라도 있으면 True. NewsroomArticleQuerySet.judged()와
        판정 기준을 공유한다(docs: for_newsroom_display() docstring 참고) — ROOM-002 캡션과
        아래 today_metric() 라벨 전환이 반드시 같은 조건이어야 어긋나지 않는다."""
        return self.articles.judged().exists()

    @property
    def today_metric(self):
        """ROOM-001 카드 지표. 5-1 예외가 열려 있는 동안은 '오늘 수집'(수집 건수 기준),
        닫히면 '오늘 통과'(filter_status=passed 기준)로 라벨과 값의 출처가 함께 바뀐다
        (docs/planning.md 뉴스룸 정책 5-1 예외 마지막 항목 — "라벨과 데이터 출처를 함께"
        바꾸라는 요건). 전환 조건은 has_filter_history 하나뿐이라 코드 수정 없이
        데이터 상태만으로 전환된다."""
        today = timezone.localtime(timezone.now()).date()
        todays = self.articles.filter(collected_at__date=today)
        if self.has_filter_history:
            return {
                "label": "오늘 통과",
                "count": todays.filter(filter_status=NewsroomArticle.STATUS_PASSED).count(),
            }
        return {"label": "오늘 수집", "count": todays.count()}


class NewsroomKeyword(models.Model):
    """뉴스룸 전용 수집 키워드. `apps.setting.models.Keyword`와 완전히 분리된 테이블이다
    (docs/planning.md 뉴스룸 정책 3번 — 안전 요건, 편의가 아니다).

    🔴 `services/collector.py`의 `collect_naver()`는 활성 수집 키워드 *전량*을 순회한다.
    뉴스룸 키워드(`교보` 단독 등)를 `Keyword`에 넣으면 본 파이프라인이 그 키워드로
    수집을 시작해 결과가 News에 쌓이고 대시보드·지식그래프까지 오염된다 — 그래서 이
    별도 테이블을 둔다. `sort`는 `Keyword.SORT_CHOICES`와 같은 어휘를 쓰되 FK로 잇지
    않는다(테이블이 다르면 실수 자체가 불가능해진다).
    """

    SORT_DATE = "date"
    SORT_SIM = "sim"
    SORT_CHOICES = [
        (SORT_DATE, "최신순"),
        (SORT_SIM, "관련도순"),
    ]

    newsroom = models.ForeignKey(Newsroom, on_delete=models.CASCADE, related_name="keywords")
    keyword = models.CharField(max_length=100)
    sort = models.CharField(max_length=10, choices=SORT_CHOICES, default=SORT_DATE)
    # 수집 건수 상한 — 키워드 행마다 갖는다(정책 3번, 전역 NAVER_DISPLAY_PER_QUERY를
    # 쓰지 않는다). 뉴스룸은 넓게 봐야 하므로 전역 기본값(5)보다 넉넉한 20을 기본값으로
    # 둔다(Naver API 상한은 100). 화면에서 언제든 조정 가능하다.
    display = models.PositiveSmallIntegerField(default=20)

    def __str__(self):
        return f"[{self.newsroom.name}] {self.keyword}"


class PaidDomain(models.Model):
    """유료 구독(페이월) 매체 도메인 목록 — 코드 필터 3종 중 10-2번(docs/planning.md
    뉴스룸 정책 6번 표). **뉴스룸 공통 전역 설정이다(뉴스룸별이 아니다)**, 정책 9번
    결정 ⑤.

    초기값은 비운다 — 매체 이름을 지어내 채우지 않는다(「무조건 팩트 기반」). 1~2단계
    운영 중 실제로 유료벽에 막힌 링크를 사람이 보고 채운다. 이 프로젝트는 SET-006
    로그 화면처럼 매일 보는 데이터가 아닌 저빈도 운영 데이터를 화면 UI 없이 셸에서
    직접 편집하는 관례를 쓴다(NewsroomArticle.judged_by와 동일한 방식) — Django admin도
    이 프로젝트 어디에도 등록돼 있지 않아 새로 여는 대신 기존 관례를 따랐다.
    """

    domain = models.CharField(max_length=255, unique=True)
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.domain


class NewsroomArticleQuerySet(models.QuerySet):
    def judged(self):
        """filter_status가 pending이 아닌 것 = 판정이 일어난 기사. 정책 5-1 예외
        ("판정 이력이 있는가")의 판별 기준을 여기 한 곳에 모은다."""
        return self.exclude(filter_status=NewsroomArticle.STATUS_PENDING)

    def for_newsroom_display(self, newsroom):
        """ROOM-002 노출 게이트(docs/planning.md 뉴스룸 정책 5번 + 5-1 예외, 2026-09-01
        신설). 조회부마다 손으로 분기를 쓰면 반드시 어긋나므로 이 메서드 한 곳에 모은다
        (PM 인계 9번, `News.objects.verified()`와 같은 이유이며 이번엔 조건이 더 복잡하다).

        원칙(5번): `filter_status == passed`인 기사만 노출한다. 게이트가 없는 게 아니라
        게이트의 주체가 RA가 아니라 LLM이다 — `News.objects.verified()` 규칙은 여기
        적용되지 않는다.

        예외(5-1, 2026-09-01): 그 뉴스룸에 filter_status가 pending이 아닌 기사가 한 건도
        없는 동안(=LLM 판정이 한 번도 일어난 적 없는 동안)은 pending도 함께 노출한다.
        1단계에는 LLM이 없어 passed가 될 경로가 아예 없으므로, 이 예외가 없으면 ROOM-002는
        1단계 내내 빈 화면이 된다. 뉴스룸마다 독립적으로 판정되며(전역 스위치 아님),
        첫 필터 실행으로 판정 이력이 한 건이라도 생기면 이 예외는 **코드 수정 없이**
        스스로 닫히고 게이트는 원래 형태(passed만)로 돌아간다.
        """
        base = self.filter(newsroom=newsroom)
        if base.judged().exists():
            return base.filter(filter_status=NewsroomArticle.STATUS_PASSED)
        return base


class NewsroomArticle(models.Model):
    """뉴스룸이 수집한 기사. `News`를 재사용하지 않고 완전히 분리된 테이블이다
    (docs/planning.md 뉴스룸 정책 4번) — ALL-001·GRAPH-001 집계 오염을 막고, 이 모델의
    filter_status(LLM 판정)가 News.status(RA 판정, 검증 게이트)와 의미가 섞이지 않게 하기
    위해서다.

    ⚠️ `News.objects.verified()` 검증 게이트는 여기 적용되지 않는다. 이 모델의 노출
    게이트는 `NewsroomArticleQuerySet.for_newsroom_display()`이고 판정 주체는 LLM이다.
    두 규칙을 섞지 말 것(`CLAUDE.md` "뉴스룸은 이 게이트 밖이다").

    기업/기술 주제 태깅을 하지 않는다 — 뉴스룸은 그룹 전반 소식을 넓게 보는 채널이라
    회사 단독 매칭이 정책적으로 허용되는 자리이며(정책 1번 표), 리서치 축 판정을
    인용하지도 인용받지도 않는다(정책 2번 "층 분리").
    """

    STATUS_PENDING = "pending"
    STATUS_PASSED = "passed"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "판정 전"),
        (STATUS_PASSED, "통과"),
        (STATUS_REJECTED, "제외"),
    ]

    newsroom = models.ForeignKey(Newsroom, on_delete=models.CASCADE, related_name="articles")
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=2000)
    # 전역 unique가 아니라 (newsroom, url_hash) 복합 unique — News.url_hash와 별개이며
    # ExcludedURL과도 연동하지 않는다(그건 RA 삭제분 재수집 차단이라 성격이 다르고,
    # 뉴스룸은 사람 삭제 기능 자체를 두지 않는다, 정책 9번 결정 ⑧).
    url_hash = models.CharField(max_length=64, db_index=True)
    body = models.TextField(blank=True)
    published_at = models.DateTimeField()
    collected_at = models.DateTimeField(auto_now_add=True)

    # LLM 판정(2단계에서 채워진다). 1단계는 전량 STATUS_PENDING으로 저장된다.
    filter_status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True,
    )
    # 판정 주체(2026-09-02 추가, 사용자 결정 — RA의 1번(정리)·2번(시사점) 작업을 News와
    # NewsroomArticle 둘 다에 적용하기로 하면서, 2단계 LLM이 붙기 전까지는 RA가 사람
    # 손으로 filter_status를 채운다). CollectionLog.actor가 이미 "수동/자동"을 같은
    # 방식으로 구분해서 그 표기(괄호 안에 구체 주체)를 그대로 따랐다. 필드명은
    # DeletedNewsRecord.judged_by/TagCorrectionRecord.judged_by 관례를 따른다 — "누가
    # 이 판정을 내렸는가"를 남기는 동일한 개념이라 이름을 이었다.
    # ⚠️ 5-1 예외("판정 이력이 있는가")는 filter_status만 본다 — 이 필드를 조건에
    # 끼워 넣지 않는다(NewsroomArticleQuerySet.judged() 참고). RA가 손으로 판정해도
    # 판정이 일어난 사실은 같으므로 예외가 닫히는 게 정상 동작이다.
    # null 허용 — pending인 동안은 아직 아무도 판정하지 않았다는 뜻이라 값이 없어야
    # 맞다(빈 문자열이 아니라 None으로 "미판정"을 표현한다).
    # ⚠️ 1단계에는 이 필드를 채우는 화면 기능이 없다 — RA가 셸에서 직접 채운다. 화면에서
    # 판정을 바꾸는 기능을 넣을지는 PM 확인 중이라 이번 라운드에는 넣지 않는다.
    JUDGED_BY_RA = "수동(RA)"
    JUDGED_BY_LLM = "자동(LLM)"
    JUDGED_BY_CHOICES = [
        (JUDGED_BY_RA, "수동(RA)"),
        (JUDGED_BY_LLM, "자동(LLM)"),
    ]
    judged_by = models.CharField(
        max_length=20, choices=JUDGED_BY_CHOICES, null=True, blank=True, default=None,
    )
    # 1단계 LLM 산출물(2단계). 1단계 동안은 항상 빈 문자열 — ROOM-002 카드가 이 경우
    # 요약 블록 자체를 렌더하지 않도록 설계돼 있다(docs/design.md ROOM-002 절).
    summary = models.TextField(blank=True)

    objects = NewsroomArticleQuerySet.as_manager()

    class Meta:
        unique_together = ("newsroom", "url_hash")
        # tie-breaker 필수(pk) — published_at 동률에서도 목록·페이지네이션 순서가
        # 흔들리지 않게 한다.
        ordering = ["-published_at", "-pk"]

    def __str__(self):
        return self.title

    @property
    def source_domain(self):
        """메타 줄("매체 · 발행시각")에 쓸 값. 이 프로젝트 어디에도 언론사명을 추출하는
        인프라가 없어(News 모델에도 없음) 매체명을 지어내는 대신 URL 도메인을 그대로
        보여준다 — 실측 가능한 값만 쓴다는 원칙(「무조건 팩트 기반」)을 지키는 최소
        구현이다."""
        try:
            netloc = urlparse(self.url).netloc
            return netloc[4:] if netloc.startswith("www.") else netloc
        except ValueError:
            return ""
