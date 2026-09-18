from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST
from .models import Report

#: pill 필터가 받아들이는 값. daily는 실사용 데이터가 없어 pill 자체를 만들지 않았으므로
#: ?period_type=daily가 와도 화이트리스트를 안 타 전체로 폴백한다(오타와 동일하게 처리).
_PERIOD_TYPE_LABELS = {"weekly": "주간", "monthly": "월간"}


# 🔴 2026-09-18 사용자 확정 — 보고서 목록·상세는 **완료된 것만** 보여준다.
# 지시: *"보고서 상세에 있는 거는 그냥 완료된 것만 보고서에서 보여야 해"*.
#
# 🔴 확정이 곧 완료가 되면서(apps/setting/views.py _confirm_report_drafts) 새로
# 만들어지는 보고서는 전부 done이다. 이 게이트가 막는 것은 **옛 데이터에 남은
# generating과 만들다 실패한 failed**다 — 사내 오픈을 앞두고 미완성 보고서가
# 사람 눈에 닿는 길을 없앤다.
#
# ⚠️ 실패한 보고서를 감추는 것이 "실패를 숨기는 것"은 아니다. 실패는 SET-010
# 4·5단계 노드가 「실행 실패」 배지로 말하고, 그 자리가 운영자가 보는 곳이다.
# 🔴 News의 verified() 게이트와 같은 성질이다 — 판정이 끝나지 않은 것을 화면에
# 올리지 않는다. 빼먹어도 에러가 나지 않고 조용히 노출되므로 새 조회 코드를 짤
# 때마다 확인해야 한다(CLAUDE.md "검증 게이트"와 같은 주의).
REPORT_VISIBLE_STATUS = "done"


def report_list(request):
    all_reports = Report.objects.filter(status=REPORT_VISIBLE_STATUS).order_by("-date_from")

    period_type = request.GET.get("period_type", "")
    if period_type not in _PERIOD_TYPE_LABELS:
        period_type = ""

    reports = all_reports.filter(period_type=period_type) if period_type else all_reports

    context = {
        "reports": reports,
        "period_type": period_type,
        "period_type_label": _PERIOD_TYPE_LABELS.get(period_type, ""),
        # 건수는 필터와 무관하게 항상 전체 기준(all_reports)으로 센다 — pill이 "보고 있는
        # 것"과 "고를 수 있는 것"을 동시에 말하면 필터마다 숫자가 흔들려 읽을 수 없다.
        "total_count": all_reports.count(),
        "weekly_count": all_reports.filter(period_type="weekly").count(),
        "monthly_count": all_reports.filter(period_type="monthly").count(),
    }
    return render(request, "reports/list.html", context)


def report_detail(request, uid):
    # 🔴 목록과 같은 게이트를 공유한다(REPORT_VISIBLE_STATUS 주석). 목록에서 감추면서
    # 상세를 열어 두면 주소를 아는 사람에게는 그대로 보인다 — News의 verified()를
    # 목록·상세 양쪽에 거는 것과 같은 이유다.
    report = get_object_or_404(Report, uid=uid, status=REPORT_VISIBLE_STATUS)
    return render(request, "reports/detail.html", {"report": report})


# 🔴 2026-09-18 신설 — 「다듬는 중」 보고서 삭제(사용자 확정: "다듬는 중인 것만").
#
# 계기 — 4단계가 만든 9월 3주차 보고서에 기간 밖 기사(8월 18일)가 들어가고 이슈가
# 상한 5건을 넘겨 9건이 실렸다. 다시 만들어야 하는데 **지우는 경로가 아예 없었다** —
# 화면에도 없고 admin에도 Report가 등록돼 있지 않았다. 게다가
# apps/setting/views.py _job_has_work("weekly")가 `Report.objects.filter(period_type,
# date_from).exists()`로 4단계 버튼을 잠그므로, **같은 주 보고서가 하나 있으면 다시
# 만들 길이 막힌다.** 실행과 검토로 끝나야 하는 일이 보고서 하나에 걸려 멈췄다.
#
# 🔴 왜 「다듬는 중」만인가 — 완료(done)로 바꾼 보고서는 이미 공유됐거나 Slack으로
# 나갔을 수 있다. 지우면 받은 사람의 링크가 깨지고 그것은 되돌릴 수 없다. 반면
# generating은 "아직 검토 중"이라는 뜻이라 버려도 잃는 것이 없다.
#
# 🔴 왜 로그인을 거는가 — /reports/는 **로그인 없이 보는 공개 화면**이다
# (apps/setting/middleware.py는 "/setting/" 접두사만 잠근다). 삭제는 운영 동작이므로
# 공개 화면에 그냥 달면 사내 오픈 뒤 누구나 지울 수 있다.
# ⚠️ 템플릿에서 버튼을 감추는 것만으로는 부족하다 — 주소를 알면 직접 호출할 수 있어서
# 뷰에서 다시 막는다. 상태 검사도 같은 이유로 여기서 한 번 더 한다.
@login_required
@require_POST
def report_delete(request, uid):
    report = get_object_or_404(Report, uid=uid)
    if report.status != "generating":
        messages.error(
            request,
            "다듬기를 마친 보고서는 지울 수 없어요. 이미 공유됐을 수 있어서예요.",
        )
        response = HttpResponse()
        response["HX-Redirect"] = reverse("report_detail", args=[report.uid])
        return response

    # 🔴 ReportNews는 through 모델이라 Report가 지워지면 함께 지워진다(CASCADE).
    # News 자체는 건드리지 않는다 — 보고서를 버리는 것이 기사를 버리는 일이 되면
    # 안 된다(apps/news/services.py has_explicit_link()가 지키는 것과 같은 선).
    title = report.title
    report.delete()
    messages.success(request, f"「{title}」을 지웠어요. 4단계에서 다시 만들 수 있어요.")
    response = HttpResponse()
    response["HX-Redirect"] = reverse("report_list")
    return response
