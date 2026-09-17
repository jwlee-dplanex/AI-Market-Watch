import uuid
from urllib.parse import urlparse

from django.db import models
from django.db.models import Q
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
    def pending_count(self):
        """판정 전(filter_status=pending) 기사 수. docs/planning.md 뉴스룸 정책 12-1
        결정 (b) "적체를 화면이 말하게 한다" 구현 — SET-010 교보 2단계 노드와
        SET-009 뉴스룸 관리가 함께 쓴다(같은 문서 12-5 PE 인계 5번). 노출 게이트
        (for_newsroom_display)를 거치지 않는다 — pending은 애초에 그 게이트 밖의
        개념(5-1 예외가 닫힌 뒤에는 화면에 안 보이는 쪽)이라 article_count와는
        다른 질문에 답한다."""
        return self.articles.filter(filter_status=NewsroomArticle.STATUS_PENDING).count()

    @property
    def has_filter_history(self):
        """5-1 예외("판정 도입 전 예외")가 닫혔는지 여부 — 이 뉴스룸에 filter_status가
        pending이 아닌 기사가 한 건이라도 있으면 True. NewsroomArticleQuerySet.judged()와
        판정 기준을 공유한다(docs: for_newsroom_display() docstring 참고) — ROOM-002 캡션과
        아래 today_metric() 라벨 전환이 반드시 같은 조건이어야 어긋나지 않는다."""
        return self.articles.judged().exists()

    @property
    def latest_message(self):
        """SET-009 발송 섹션(templates/setting/_newsroom_message.html)이 쓰는 가장
        최근 발송 레코드 1건 또는 None(docs/planning.md 뉴스룸 정책 12-3 (b)(c)).
        목록이 아니다 — 그 화면은 항상 최신 1건만 보여준다."""
        return self.messages.order_by("-created_at", "-pk").first()

    @property
    def mark_sent_url(self):
        """「보냈다고 표시하기」 POST URL 문자열. 최신 발송 레코드가 없으면 빈
        문자열을 돌려준다 — _newsroom_message.html이 그 경우 버튼을 안전하게
        비활성으로 떨어뜨린다(그 조각의 컨텍스트 계약)."""
        message = self.latest_message
        if not message:
            return ""
        from django.urls import reverse
        return reverse("setting_newsroom_message_mark_sent", args=[message.pk])

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

    @property
    def compose_targets(self):
        """3단계(발송문) 새 재료 — docs/planning.md 뉴스룸 정책 "회차 경계는
        증분이다"(PM 확정, 2026-09-17 사고 조사): passed 이고 duplicate_of가
        없고 **기존 모든 NewsroomMessage(실패 포함)의 포함 기사 합집합에 없는**
        기사만 대상이다. 「한 번 실린 기사는 다시 싣지 않는다」의 실행부다.

        🔴 SET-010 배지(`apps/setting/views.py`
        `_newsroom_compose_has_new_material()`)와 실제 실행
        (`services/runner.py` `_run_newsroom_compose()`)이 반드시 같은 것을
        봐야 한다(PM 지시 "배지와 두 벌로 짜지 말고 한 군데로 뽑아 양쪽이 같은
        것을 부르게 할 것") — 09-16에 배지만 이 조건으로 고쳐지고 실행은
        고쳐지지 않아 갈렸던 것이 2026-09-17 "14건에 이전 회차까지 담김"
        사고의 원인이었다. 이 프로퍼티 하나를 양쪽이 그대로 부른다."""
        already_sent = self.messages.all().article_ids()
        return self.articles.filter(
            filter_status=NewsroomArticle.STATUS_PASSED, duplicate_of__isnull=True,
        ).exclude(pk__in=already_sent)

    @property
    def past_messages(self):
        """SET-009 발송 섹션 "이전 초안 전체 보기" 목록(docs/design.md
        "SET-009 · 발송 섹션" ⑩ PE 인계) — `latest_message`를 뺀 나머지
        초안, 최신순. 실패 초안도 빼지 않는다(다음 회차의 기준점이라 지우면
        경계가 틀어진다는 정책 때문에 목록에서도 빼면 안 된다). DOM에 한꺼번에
        실리는 것을 막으려 최근 20건으로 끊는다(같은 절 "목록 상한")."""
        latest = self.latest_message
        qs = self.messages.all()
        if latest:
            qs = qs.exclude(pk=latest.pk)
        return list(qs[:20])


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


class NewsroomAffiliate(models.Model):
    """관계사 태그 대상(2026-09-08 신설, 사용자 확정 — 교보생명·교보증권·교보문고·
    교보라이프플래닛·SBI저축은행·교보자산신탁·디플래닉스 일곱). 채널(`Newsroom`)에
    붙는 데이터라 채널마다 다른 관계사 목록을 가질 수 있다.

    ⚠️ `NewsroomKeyword`(수집 키워드)와는 완전히 다른 테이블이다 — "교보자산신탁"·
    "디플래닉스"는 검색하지 않지만("교보" 키워드로 들어온 기사 안에서 잡힌다) 태그는
    달아야 하므로 키워드 테이블을 재사용할 수 없다. 그룹 전체를 가리키는 "교보"는
    관계사가 아니므로 여기 등록하지 않는다.

    name/aliases 구조를 `apps.setting.models.Organization`과 똑같이 맞췄다 —
    `services/collector.py`의 `_find_matching_entities()`(역방향 삼킴 방지 포함)를
    그대로 재사용하기 위해서다. 새 별칭을 추가하기 전에는 그 함수와 같은 기준으로
    다른 관계사의 이름/별칭 안에 삼켜지지 않는지 등록 전 대조가 필요하다(RA가 기업
    등록 때 하는 양방향 대조와 같은 방식).

    🔴 이 모델에는 태그 교정 경로를 만들지 않는다(2026-09-08 사용자 확정) — 교보
    소식은 그룹 소식 채널이라 배경 언급이라도 관계사 태그가 맞다고 보고, 매칭 결과를
    그대로 쓴다.
    """

    newsroom = models.ForeignKey(Newsroom, on_delete=models.CASCADE, related_name="affiliates")
    name = models.CharField(max_length=100)
    aliases = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return self.name


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

        중복 배제(2026-09-17, 사용자 결정 "목록이 대표만 보이게 한다"): `duplicate_of`가
        채워진 기사(대표가 아니라 같은 사건의 나머지)는 여기서 제외한다. 행 자체는
        지우지 않는다 — 교보 축에는 재수집 차단 장치(ExcludedURL 대응물)가 없어
        지우면 다음 수집에 그대로 다시 들어오고, 뉴스룸은 애초에 사람 삭제 기능이
        없다(정책 9번 결정 ⑧). 이 큐어리셋 하나가 ROOM-002 목록, `article_count`
        캡션, ROOM-003 이전/다음(`_adjacent_article()`)을 전부 통과하므로 대표 하나만
        보이는 것이 세 자리 모두에서 자동으로 같이 맞는다 — 손으로 세 곳을 따로
        고치면 반드시 어긋난다(위 `article_count` docstring과 같은 이유).

        SET-009 관리 화면은 이 메서드를 쓰지 않는다(예: `pending_count`,
        `apps/setting/views.py`의 적체 줄) — 그 화면은 "무엇을 판정해야 하는가"를
        보여주는 운영 화면이라 대표든 중복이든 실제로 쌓인 기사 전량이 근거가 돼야
        한다. 여기서 중복을 걸러도 그 화면들은 원래 이 게이트를 거치지 않으므로
        영향이 없다.
        """
        base = self.filter(newsroom=newsroom, duplicate_of__isnull=True)
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

    # URL에 순번 pk를 그대로 노출하지 않는다 — News.uid/Report.uid/Newsroom.uid와
    # 동일 패턴(ROOM-003, 2026-09-02 추가).
    uid = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
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
    # 제목 키워드 검사(2026-09-15 PE 신설, docs/planning.md 뉴스룸 정책 13번) — 2단계
    # LLM을 부르기 전에 코드가 직접 내리는 판정. 사유가 아니라 주체를 남기는 칸이라
    # (13-2 ④) 값 하나를 더 두는 것으로 충분하다. 가운뎃점·줄표는 쓰지 않는다(13-6 4번).
    JUDGED_BY_CODE_TITLE_RULE = "코드(제목 규칙)"
    JUDGED_BY_CHOICES = [
        (JUDGED_BY_RA, "수동(RA)"),
        (JUDGED_BY_LLM, "자동(LLM)"),
        (JUDGED_BY_CODE_TITLE_RULE, "코드(제목 규칙)"),
    ]
    judged_by = models.CharField(
        max_length=20, choices=JUDGED_BY_CHOICES, null=True, blank=True, default=None,
    )
    # 1단계 LLM 산출물(2단계). 1단계 동안은 항상 빈 문자열 — ROOM-002 카드가 이 경우
    # 요약 블록 자체를 렌더하지 않도록 설계돼 있다(docs/design.md ROOM-002 절).
    summary = models.TextField(blank=True)

    # 유입 키워드(2026-09-04 추가, PM 1순위 권고) — "어느 NewsroomKeyword로 수집됐는가"를
    # 그대로 적어 둔다. 관계사 분류 필드가 아니다 — PM 표현 그대로 "수집이 공짜로 아는
    # 사실을 적는 것이지 분류가 아니다." ROOM-002 세 층 대시보드의 관계사별 그룹핑은
    # 이 필드의 1차 근사일 뿐이고, 키워드별 통과율(filter_status 대비) 측정에도 쓴다.
    # on_delete=SET_NULL — 키워드 행을 지워도 이미 수집된 기사(과거 사실)는 남아야 한다.
    # ⚠️ unique_together=("newsroom", "url_hash")라 같은 기사가 두 번째 키워드로 다시
    # 걸려도 저장되지 않는다(위 collect_newsroom()의 skipped_dup 경로) — 그 경우 이 필드는
    # 처음 잡힌 키워드만 기록하고 두 번째 키워드는 영영 남지 않는다. PM이 이 한계를
    # 인지한 채로 그대로 두기로 했다(뒤로 미루면 관측 구간이 통째로 날아가는 것이 더
    # 큰 손해라는 판단).
    source_keyword = models.ForeignKey(
        "NewsroomKeyword", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="articles",
    )

    # AI 관련 여부(2026-09-04 추가) — ROOM-002 "헤드라인" 층의 선별 기준. 판정 주체는
    # RA(사람)다. LLM 자동 판정 로직은 아직 없다(2단계 스코프) — 이 필드는 RA가 셸에서
    # 직접 채운다(judged_by와 같은 운영 관례). null=미판정, True=AI 관련, False=AI 아님.
    is_ai_related = models.BooleanField(null=True, blank=True, default=None)

    # 관계사 태그(2026-09-08 추가) — News.organizations와 같은 구조. 수집 시점에
    # 제목+본문에서 매칭해 채운다(services.py collect_newsroom()). 교정 경로는 없다 —
    # NewsroomAffiliate docstring 참고.
    affiliates = models.ManyToManyField(NewsroomAffiliate, blank=True, related_name="articles")

    # 분량 축(2026-09-14 추가, 정책 6-3절 (f)) — 이 기사의 body가 원문 전문이 아니라
    # 네이버 요약문 잔여물이라는 뜻이다. 판별은 길이가 아니라 크롤 성공 여부다:
    # services/crawler.py의 fetch_article_body()가 None을 돌려줬을 때만 True로
    # 채운다(collect_newsroom() 참고). 이름을 "crawl_failed"로 하지 않은 이유는 그건
    # 수집 내부 사정의 이름이고, 화면(ROOM-003)이 묻는 것은 "잘렸는가"이기 때문이다 —
    # 필드 이름과 화면 조건의 방향이 같아야 뷰·템플릿에 부정 연산이 붙지 않는다.
    #
    # 🔴 실체 축(마침표로 끝나는 완결된 서술문이 있는가)을 위한 필드는 별도로 두지
    # 않는다 — 그 기준에 걸린 기사는 애초에 저장하지 않으므로 표시할 행이 없다.
    #
    # ⚠️ 소급분(이 필드 도입 이전에 수집된 기사)은 len(body) < 200으로 채워졌다 —
    # 크롤 성공이 본문 200자 이상을 보증하므로 이는 추정이 아니라 동치다. 다만 이
    # 소급은 이데일리 메뉴 덤프 9건(398~414자, 실체 축에 걸려야 했지만 이 필드
    # 도입 전에 이미 저장된 데이터라 정정하지 않는다)을 잡지 못해 그 9건은 False로
    # 남는다 — 오류가 아니라 정의대로다. 따라서 body_is_truncated == False를 "전문이
    # 확보됐다"로 읽으면 안 된다. 정확한 뜻은 "요약문 잔여물이 아니다"까지다.
    body_is_truncated = models.BooleanField(default=False)

    # 2단계 LLM 산출물 둘(2026-09-15 PE 신설, docs/planning.md 뉴스룸 정책 12-2 (c)
    # "필드 형태와 이름은 PE가 정한다") — filter_status/judged_by/summary만으로는
    # 지침 7(파급력 정렬)과 8·10-5(중복 묶기)의 산출물을 담을 자리가 없어(실측,
    # 12-2 (c) 표) 그대로 버려지고 있었다. 둘 다 통과(passed)한 기사에만 채운다 —
    # 제외(rejected)·판정 전(pending)은 None으로 남는다.
    impact_rank = models.PositiveSmallIntegerField(
        null=True, blank=True, default=None,
        help_text="2단계 LLM이 매긴 비즈니스 파급력 순위(1이 가장 크다). 같은 실행 "
                   "배치 안에서만 비교 가능하다 — 서로 다른 날 배치의 순위를 "
                   "직접 비교하지 않는다. 3단계 발송문이 이 순서를 그대로 따른다 "
                   "(정책 12-2 표 '2단계는 그 순서를 따름').",
    )
    # self-FK를 택한 이유 — 정책 12-2 (c)가 "대표 1건만 남기고 나머지는 묶음으로
    # 표시로 정했다"와 "중복으로 묶인 기사를 rejected로 떨어뜨리지 않는다"(제외와
    # 중복은 다른 뜻이라 filter_status 한 칸에 같이 담지 않는다) 둘을 요구한다.
    # 대표 기사는 duplicate_of가 None이고, 같은 사건의 나머지 기사는 그 대표를
    # 가리킨다 — 그룹을 담을 별도 모델을 두지 않아도 "이 기사의 대표가 무엇인가"
    # 하나의 질문으로 묶음이 그대로 표현된다.
    duplicate_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="duplicates",
        help_text="같은 사건을 다루는 대표 기사. 대표 기사 자신은 None이다. filter_status는 "
                   "두 기사 모두 passed로 그대로 둔다 — 이 필드로만 묶고 제외 처리하지 않는다. "
                   "대표만 펼쳐 보이고 나머지를 묶음으로 접어 보이는 것은 화면(PD) 몫이다.",
    )

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


class NewsroomMessageQuerySet(models.QuerySet):
    def article_ids(self):
        """이 쿼리셋에 속한 메시지들이 담았던 기사 pk 집합(합집합, 실패 초안도
        포함 — status로 거르지 않는다). `Newsroom.compose_targets`와
        `NewsroomMessage.new_article_count`가 "이미 어느 발송문에 실렸는가"를
        묻는 유일한 자리로 이 메서드를 함께 쓴다(회차 경계 정의를 두 벌로
        나누지 않는다, 2026-09-17 PM 지시)."""
        return set(
            NewsroomArticle.objects.filter(messages__in=self).values_list("pk", flat=True)
        )


class NewsroomMessage(models.Model):
    """뉴스룸 3단계(발송문) 산출물 — 발송 레코드 1건(docs/planning.md 뉴스룸 정책
    12-3 (b) "담을 자리가 없다(실측). 발송 레코드를 별도 모델로 신설한다"). 기사별
    요약은 이미 2단계 산출물(NewsroomArticle.summary)이고 ROOM-002가 그것을 쓴다 —
    이 모델이 다시 만들면 같은 값이 두 곳에 생겨 정본이 둘이 된다. 여기 담는 것은
    그 요약들을 조립한 "한 덩어리 글" 하나뿐이다.

    🔴 `Newsroom`에 칸을 더하지 않고 별도 모델로 둔 이유(12-3 (b) 표) — 발송문은
    날마다 한 건씩 쌓이는 이력이다. 채널 레코드에 넣으면 어제 것이 오늘 것에
    덮인다.

    🔴 발송 코드가 없다(2026-09-15 사용자 확정, "Slack 메시지는 구현하지마"). 사람이
    하는 일은 이 레코드의 body를 읽고 복사해서 Slack에 직접 붙여넣고, 여기로 돌아와
    "보냈다고 표시하기"를 누르는 것뿐이다(12-3 (c)) — sent_at이 그 표시를 담는다.
    """

    STATUS_DRAFT = "draft"
    STATUS_SENT_MANUAL = "sent_manual"
    # 🔴 지금 쓰이지 않아도 미리 넣어 둔다(12-3 (d), PM 지시) — 나중에 4단계(자동
    # 발송)를 만들 때 상태 어휘를 늘리면 기존 행의 뜻이 소급으로 바뀐다. 뉴스룸은
    # filter_status 문자열(excluded 대 rejected)에서 이미 한 번 그 실패를 겪었다.
    STATUS_SENT_AUTO = "sent_auto"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "초안"),
        # 🔴 "수동 발송함"에서 "발송 표시"로 옮겼다(2026-09-16 PE 판단, docs/design.md
        # SET-009 절 22차 정렬 항목). 실제로 Slack에 보낸 것이 아니라 사람이
        # "보냈다"고 화면에 표시한 것이라, "발송함"이라고 하면 시스템이 보낸 것처럼
        # 읽힌다. 시각 캡션이 이미 "09/16 11:14 발송 표시"로 정리돼 있어 같은
        # 낱말로 맞췄다 — 배지도 이름표 자리라 문어체 명사형이어야 하는데(1.0.3),
        # "표시"는 초안·실패처럼 순수 명사라 그 규칙에도 맞는다.
        (STATUS_SENT_MANUAL, "발송 표시"),
        (STATUS_SENT_AUTO, "자동 발송함"),
        (STATUS_FAILED, "실패"),
    ]

    newsroom = models.ForeignKey(Newsroom, on_delete=models.CASCADE, related_name="messages")
    # 이 발송문이 다루는 날짜(만들어진 시점의 로컬 날짜). "어느 채널의 며칠 치
    # 소식인가"를 남긴다(12-3 (b) 표 "뉴스룸 FK, 대상 날짜").
    date = models.DateField()
    # 메시지 본문 원문 — 이 모델의 본체다. 사람이 여기서 그대로 복사해 Slack에
    # 붙여넣는다. 검증에 걸려도(아래 status) 지우지 않는다 — 지우면 지침 1(전수
    # 나열)을 LLM이 어떻게 어겼는지가 사라진다(12-3 (e)).
    body = models.TextField(blank=True)
    # 포함 기사 — 생성 시점의 집합을 얼려 둔다. 그날 통과분(filter_status)은
    # 재판정으로 나중에 바뀔 수 있어, 코드 검증(아래 status)과 article_count가
    # 대조할 대상은 이 M2M이 얼려 둔 집합이어야 한다(12-3 (b) 표).
    articles = models.ManyToManyField(NewsroomArticle, blank=True, related_name="messages")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    # 🔴 사람이 "보냈다고 표시한" 시각 — 4단계(자동 발송) 시각과 같은 칸을 쓰지
    # 않는다(12-3 (d)). 이 모델에는 자동 발송 코드 자체가 없어 지금은 그 값이 생길
    # 일이 없지만, 나중에 생겨도 별도 칸이 필요하다는 뜻을 필드 하나로 못박아 둔다.
    sent_at = models.DateTimeField(null=True, blank=True)
    # 코드 검증(정책 12-3 (e)) 실패 사유. status가 실패일 때만 채워진다.
    error = models.TextField(blank=True)

    objects = NewsroomMessageQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.newsroom.name} {self.date}"

    @property
    def article_count(self):
        """SET-009 발송 섹션이 보이는 "기사 N건" 줄. 저장 시점에 얼린 articles
        집합의 크기이지, 지금 이 순간의 통과 기사 수가 아니다."""
        return self.articles.count()

    @property
    def status_label(self):
        """SET-009 발송 섹션이 그대로 찍는 배지 문구("초안"/"발송 표시"/"실패").
        choices의 한국어 라벨을 그대로 쓴다 — 템플릿이 문자열을 하드코딩하지
        않는다."""
        return self.get_status_display()

    @property
    def new_article_count(self):
        """SET-009 "이전 초안 전체 보기" 목록·최신 카드가 함께 쓰는 "이 회차 새
        기사" 수(docs/design.md "SET-009 · 발송 섹션" ④번) — 이 메시지에
        담긴 기사 가운데 이 메시지보다 **먼저 생성된** 메시지에는 한 번도
        담긴 적 없는 것의 개수다. "먼저"는 created_at, 동률이면 pk로 가른다
        (Meta.ordering과 같은 tie-breaker).

        `Newsroom.compose_targets`와 같은 정의(`NewsroomMessageQuerySet.
        article_ids()`)를 그대로 쓴다 — 회차 경계를 두 벌로 나누지 않는다."""
        earlier = self.newsroom.messages.filter(
            Q(created_at__lt=self.created_at)
            | Q(created_at=self.created_at, pk__lt=self.pk)
        ).article_ids()
        return self.articles.exclude(pk__in=earlier).count()
