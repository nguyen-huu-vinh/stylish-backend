import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request

_hits: dict = defaultdict(deque)
_lock = Lock()


def _client_ip(request: Request) -> str:
    # Sau proxy của Render, IP thật nằm ở đầu X-Forwarded-For
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(name: str, limit: int, window_seconds: int):
    """Dependency giới hạn `limit` lần gọi / `window_seconds` giây cho mỗi IP.

    Lưu trong bộ nhớ tiến trình: đủ để chặn dò mật khẩu/spam trên 1 worker.
    """

    def dependency(request: Request):
        key = (name, _client_ip(request))
        now = time.monotonic()
        with _lock:
            hits = _hits[key]
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                retry = int(window_seconds - (now - hits[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail="Bạn thao tác quá nhanh, vui lòng thử lại sau ít phút.",
                    headers={"Retry-After": str(retry)},
                )
            hits.append(now)

    return dependency
