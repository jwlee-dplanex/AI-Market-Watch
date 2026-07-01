from apps.news.models import News


def sidebar_context(request):
    try:
        last = News.objects.order_by("-collected_at").first()
        last_collected_at = last.collected_at.strftime("%m/%d %H:%M") if last else None
    except Exception:
        last_collected_at = None
    return {"last_collected_at": last_collected_at}
