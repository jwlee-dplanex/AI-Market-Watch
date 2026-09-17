"""SET-010 실행 그래프(`setting_run_graph`) 요청 스코프 성능 캐시.

점검 지적 ① — `_representative_run_job()`이 job_key 아홉 개마다 RunJob을
latest/pending/confirmed로 각각 개별 SELECT하고(최대 21회), `cleanup_ab_split()`/
`insight_ab_split()`이 배지·적체 줄·흐름 줄·선행 잠금 판정에서 각각 다시 계산되는
문제(중복 계산)를 고치기 위한 인프라. 처방은 "요청 1회당 한 번만 계산해 재사용"이다.

🔴 전역(프로세스 전체) 캐시로 만들면 안 된다 — 3초 폴링 화면이라 RunJob 상태가
계속 바뀌는데, 요청을 넘어 캐시가 살아 있으면 방금 시작/중단한 실행이 다음
폴링에도 반영되지 않는 조용한 버그가 된다. 스레드 로컬을 쓰는 이유는 gunicorn
(sync·gthread 모두)과 runserver가 요청 하나를 스레드 하나에서 처음부터 끝까지
동기로 처리하기 때문이다(이 프로젝트에 비동기 뷰가 없다) — "요청 시작 시 한 번
비운다"만 지키면 스레드 로컬로 충분히 안전하다.

캐시 비우기는 apps/setting/middleware.py의 PerfCacheMiddleware가 요청마다
한 곳에서 담당한다(뷰마다 흩어 두면 새 진입점이 생길 때 리셋을 빠뜨리기 쉽다 —
이 저장소가 반복해서 겪은 "조용한 실패" 패턴, 템플릿 주석·검증 게이트 누락과
같은 유형)."""
import threading

_local = threading.local()


def reset_perf_cache():
    """요청 시작마다 호출 — 이전 요청(같은 스레드가 처리한)의 값이 새 요청에
    새지 않게 캐시를 통째로 비운다."""
    _local.cache = {}


def cache_get_or_set(key, compute):
    """캐시에 key가 있으면 그대로 돌려주고, 없으면 compute()를 불러 채운 뒤
    돌려준다. 미들웨어를 거치지 않은 경로(management command, shell 등)에서
    불리면 캐시 자체가 없어 매번 새로 계산한다 — 캐시가 없어도 결과는 항상
    맞다, 다만 그 경로에서는 느릴 뿐이다(정확성이 속도보다 우선)."""
    cache = getattr(_local, "cache", None)
    if cache is None:
        return compute()
    if key not in cache:
        cache[key] = compute()
    return cache[key]
