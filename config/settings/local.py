from .base import *

# DEBUG·ALLOWED_HOSTS는 .env에서 관리한다(2026-08-04 변경).
# 종전에는 여기서 True/리스트를 하드코딩해 .env 값을 덮어쓰고 있었는데, 사내망
# 공유처럼 값을 바꿔야 할 때마다 코드를 고쳐야 했다. default는 "로컬 개발"에
# 맞춰 두되(.env에 키가 없어도 개발이 안 막히게), .env에 값이 있으면 그쪽이 이긴다.
#
# 팀 공유 시 .env에서:
#   DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,<내 사설 IP>
#   DJANGO_DEBUG=False        ← 에러 페이지에 소스·설정값이 노출되지 않게
# DEBUG=False로 두면 runserver가 정적 파일을 안 뿌리므로 --insecure 를 함께 쓴다.
DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
