"""로컬에서 손으로 한 데이터 교정을 프로덕션에도 같게 적용한다.

🔴 2026-10-06 신설. 계기 — 사용자 지시 *"로컬과 ec2는 무조건 동일하게 가야해"*와
cutover 이후 확정된 *"로컬에서 EC2로 가는 DB 방향은 영구히 닫힌다"*가 부딪히는
자리가 생겼다. 덤프를 다시 올리는 것은 금지지만, **같은 교정을 양쪽에서 각자
돌리는 것**은 이관이 아니므로 그 금지에 어긋나지 않는다(사용자 확정).

🔴 이 명령은 멱등하다. 이미 적용된 교정은 건너뛰고, **대상 레코드가 없으면 그것도
건너뛴다.** EC2는 2026-09-11 덤프에 2026-09-21 cutover를 더한 상태로 동결돼 있어
그 뒤 로컬에서 수집된 기사가 아예 없다 — 없는 pk를 만나면 조용히 지나가야 양쪽에서
같은 명령을 그대로 쓸 수 있다.

⚠️ pk로 레코드를 특정한다. 양쪽이 같은 덤프에서 출발했기 때문에 성립하는 전제이고,
그래서 **EC2가 수집을 시작하면 이 방식은 더 쓸 수 없다.** 그때는 uid나 url_hash로
찾는 방식으로 바꿔야 한다(News.uid, NewsroomArticle은 url_hash).

쓰는 법 — 기본은 미리보기이고, 실제로 바꾸려면 --apply를 붙인다.

    venv/Scripts/python manage.py sync_data_fixes --settings=config.settings.local
    venv/Scripts/python manage.py sync_data_fixes --apply --settings=config.settings.local

프로덕션에서는 설정만 바꾼다.

    venv/bin/python manage.py sync_data_fixes --apply --settings=config.settings.production
"""
from django.core.management.base import BaseCommand
from django.db import transaction

#: 중복 묶기 — (대표 pk, [묶을 pk, ...]).
#:
#: 🔴 대표에 이미 묶여 있던 기사도 같은 대표로 옮긴다. 안 옮기면 a -> b -> c 체인이
#: 생기고 "대표는 duplicate_of가 없다"는 불변식이 **오류 없이** 깨진다. 실제로
#: 2026-10-06에 4346 -> 4343 -> 4339를 만들었다가 전수 검사로 찾아 고쳤다.
NEWS_DUPLICATES = [
    # 삼성화재 피난훈련 정량평가 시스템(2026-09-20 발행 4건).
    # 대표 4339는 본문 1335자로 가장 충실하고 특허 출원과 병목구간 분석을 모두 담았다
    # (4343은 1172자, 4345는 908자). 🔴 **이 넷은 9/21 덤프 안에 있어 EC2에도 있다.**
    (4339, [4343, 4345, 4346]),
]

#: 교보 소식 중복 묶기 — 같은 모양이되 NewsroomArticle 대상이다.
#:
#: ⚠️ 아래 묶음은 대표가 9/21 이후 수집분이어서 **EC2에는 대상이 없다.** 그래도
#: 적어 둔다 — 로컬에서 두 번 돌려도 안전한지 확인하는 자리이고, 나중에 cutover가
#: 또 일어나면 그때는 EC2에도 적용돼야 하기 때문이다.
NEWSROOM_DUPLICATES = [
    # SBI저축은행 사명 변경(09/29~10/01, 세 배치에 걸쳐 같은 사건이 대표 셋으로 떴다).
    (430, [370, 412, 399, 400, 404, 413, 414, 415]),
    # 교보라이프플래닛 흡수(09/16과 09/29).
    (373, [309]),
]

#: 사실 오류 문구 교정 — (모델 경로, pk, [(필드, 틀린 것, 바른 것), ...]).
#:
#: 🔴 근거 기사에 없는 값을 쓴 자리다. 「가드레일 28개」는 기사에 개수가 아예 없고
#: 유일한 28이 「평균 대비 28.2점 높은」이었다. 「21개 과제」는 기사가 「은행에서
#: 19개의 AI 과제를, 카드에서 2개의 AI 과제를 도출해」라고 적은 것을 더한 값이고,
#: 프롬프트 규칙 「값이 여럿이면 뭉개지 않고 그대로 쓰거나 쓰지 않는다」 위반이다.
#:
#: ⚠️ 문장 수를 바꾸지 않는 치환이라 RunDraft.content_keep 인덱스가 그대로 유효하다.
TEXT_FIXES = [
    ("apps.news.models.Insight", 290, [
        ("content", "금융 특화 가드레일 28개를 마련해", "금융 특화 가드레일을 개발해"),
        ("content", "21개 과제를 도출했다", "은행 19개와 카드 2개 과제를 도출했다"),
        ("content_short", "금융 특화 가드레일 28개를 마련해", "금융 특화 가드레일을 개발해"),
        ("content_short", "21개 과제를 도출했다", "은행 19개와 카드 2개 과제를 도출했다"),
    ]),
    ("apps.reports.models.Report", 27, [
        ("overview", "금융 특화 가드레일 28개", "금융 특화 가드레일"),
        ("content", "금융 특화 가드레일 28개를 마련해", "금융 특화 가드레일을 개발해"),
        ("content", "21개 과제를 도출했다", "은행 19개와 카드 2개 과제를 도출했다"),
        ("content_short", "금융 특화 가드레일 28개를 마련해", "금융 특화 가드레일을 개발해"),
        ("content_short", "21개 과제를 도출했다", "은행 19개와 카드 2개 과제를 도출했다"),
    ]),
]

#: 축약본을 다시 조립할 보고서 pk.
#:
#: 🔴 2026-10-02 이전에 확정된 보고서는 이슈 머리(`###`)가 보호받지 않아, LLM이 그
#: 블록 문장을 하나도 고르지 않으면 **머리와 본문이 빠지고 `참고:` 줄만 남았다.**
#: Report 27이 그랬다(긴 버전 머리 5개, 짧은 버전 3개). block_prefix를 넣은 코드가
#: 배포된 **뒤에** 이 교정을 돌려야 한다 — deploy.sh 다음이다.
SHORT_REBUILDS = [27]


def _resolve(path):
    module_path, name = path.rsplit(".", 1)
    from importlib import import_module

    return getattr(import_module(module_path), name)


class Command(BaseCommand):
    help = "로컬에서 손으로 한 데이터 교정을 같게 적용한다(멱등, 기본은 미리보기)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="실제로 저장한다. 없으면 무엇이 바뀔지만 보여준다.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        self.changed = 0
        self.skipped = 0

        self.stdout.write("=== 중복 묶기 (News) ===")
        self._merge_duplicates("apps.news.models.News", NEWS_DUPLICATES, apply)

        self.stdout.write("=== 중복 묶기 (NewsroomArticle) ===")
        self._merge_duplicates(
            "apps.newsroom.models.NewsroomArticle", NEWSROOM_DUPLICATES, apply,
        )

        self.stdout.write("=== 문구 교정 ===")
        self._fix_text(apply)

        self.stdout.write("=== 축약본 재조립 ===")
        self._rebuild_short(apply)

        self.stdout.write("=== 불변식 전수 검사 ===")
        self._assert_no_chains("apps.news.models.News")
        self._assert_no_chains("apps.newsroom.models.NewsroomArticle")

        verb = "바꿨어요" if apply else "바꿀 거예요"
        self.stdout.write(
            self.style.SUCCESS("%d곳을 %s. %d곳은 건너뛰었어요." % (self.changed, verb, self.skipped))
        )
        if not apply and self.changed:
            self.stdout.write("실제로 적용하려면 --apply 를 붙여 주세요.")

    # -- 중복 묶기 ----------------------------------------------------------
    def _merge_duplicates(self, model_path, groups, apply):
        model = _resolve(model_path)
        for rep_pk, member_pks in groups:
            rep = model.objects.filter(pk=rep_pk).first()
            if rep is None:
                self.stdout.write("  pk=%s 대표가 없어요. 이 묶음을 건너뛰어요." % rep_pk)
                self.skipped += 1
                continue
            if rep.duplicate_of_id is not None:
                # 🔴 대표가 이미 다른 기사에 묶여 있으면 손대지 않는다. 이 상태로
                # 멤버를 붙이면 체인이 생긴다.
                self.stdout.write(
                    self.style.WARNING(
                        "  pk=%s 가 이미 %s에 묶여 있어요. 사람이 봐야 해요."
                        % (rep_pk, rep.duplicate_of_id)
                    )
                )
                self.skipped += 1
                continue

            # 멤버에 이미 묶여 있던 기사까지 같은 대표로 끌어온다(체인 방어).
            targets = set(member_pks)
            for extra in model.objects.filter(duplicate_of_id__in=member_pks):
                targets.add(extra.pk)

            for pk in sorted(targets):
                row = model.objects.filter(pk=pk).first()
                if row is None:
                    self.skipped += 1
                    continue
                if row.duplicate_of_id == rep_pk:
                    continue
                self.stdout.write("  pk=%s: %s -> %s" % (pk, row.duplicate_of_id, rep_pk))
                self.changed += 1
                if apply:
                    with transaction.atomic():
                        row.duplicate_of = rep
                        fields = ["duplicate_of"]
                        # 🔴 교보 축은 순위를 대표에만 둔다. 묶이는 기사의 순위를
                        # 비우지 않으면 화면이 그 기사를 대표로 착각한다.
                        if hasattr(row, "impact_rank") and row.impact_rank is not None:
                            row.impact_rank = None
                            fields.append("impact_rank")
                        row.save(update_fields=fields)

    # -- 문구 교정 ----------------------------------------------------------
    def _fix_text(self, apply):
        for model_path, pk, replacements in TEXT_FIXES:
            model = _resolve(model_path)
            row = model.objects.filter(pk=pk).first()
            if row is None:
                self.stdout.write("  %s pk=%s 가 없어요. 건너뛰어요." % (model_path, pk))
                self.skipped += 1
                continue
            touched = []
            for field, old, new in replacements:
                cur = getattr(row, field) or ""
                if old not in cur:
                    continue
                setattr(row, field, cur.replace(old, new))
                touched.append(field)
                self.stdout.write("  %s pk=%s %s: %r -> %r" % (model_path, pk, field, old, new))
                self.changed += 1
            if touched and apply:
                with transaction.atomic():
                    row.save(update_fields=sorted(set(touched)))

    # -- 축약본 재조립 ------------------------------------------------------
    def _rebuild_short(self, apply):
        from apps.reports.models import Report
        from apps.setting.models import RunDraft
        from services.llm import build_short_field

        for pk in SHORT_REBUILDS:
            report = Report.objects.filter(pk=pk).first()
            if report is None:
                self.stdout.write("  Report pk=%s 가 없어요. 건너뛰어요." % pk)
                self.skipped += 1
                continue
            draft = report.run_drafts.filter(
                draft_type__in=(RunDraft.TYPE_WEEKLY, RunDraft.TYPE_MONTHLY),
            ).first()
            if draft is None:
                self.stdout.write("  Report pk=%s 의 초안이 없어 문장 번호를 못 찾아요." % pk)
                self.skipped += 1
                continue
            # 🔴 draft.content 가 아니라 report.content 로 만든다. 문구 교정이
            # 보고서에만 반영돼 있어서, 초안으로 만들면 옛 문구가 되살아난다.
            rebuilt = build_short_field(
                report.content or "", draft.content_keep,
                always_keep_prefix="참고:", block_prefix="###",
            )
            if not rebuilt or rebuilt == (report.content_short or ""):
                self.stdout.write("  Report pk=%s 축약본은 그대로예요." % pk)
                continue
            self.stdout.write(
                "  Report pk=%s 축약본: 이슈 머리 %d개 -> %d개, %d자 -> %d자"
                % (pk, (report.content_short or "").count("###"), rebuilt.count("###"),
                   len(report.content_short or ""), len(rebuilt))
            )
            self.changed += 1
            if apply:
                with transaction.atomic():
                    report.content_short = rebuilt
                    report.save(update_fields=["content_short"])

    # -- 불변식 -------------------------------------------------------------
    def _assert_no_chains(self, model_path):
        model = _resolve(model_path)
        chains = [
            (row.pk, row.duplicate_of_id, row.duplicate_of.duplicate_of_id)
            for row in model.objects.exclude(duplicate_of__isnull=True)
            .select_related("duplicate_of")
            if row.duplicate_of.duplicate_of_id is not None
        ]
        name = model_path.rsplit(".", 1)[-1]
        if chains:
            self.stdout.write(self.style.ERROR(
                "  %s 체인 %d건이 남았어요: %s" % (name, len(chains), chains[:10])
            ))
        else:
            self.stdout.write("  %s 체인 0건" % name)
