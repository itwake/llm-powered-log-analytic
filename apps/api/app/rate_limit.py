from __future__ import annotations

import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.config import Settings
from app.core.security import hash_token


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, app_settings: Settings) -> None:
        super().__init__(app)
        self.settings = app_settings
        self._windows: dict[str, tuple[float, int]] = {}

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.settings.rate_limit_enabled or not request.url.path.startswith("/api"):
            return await call_next(request)

        limit = max(1, self.settings.rate_limit_requests_per_minute)
        key = self._request_key(request)
        now = time.monotonic()
        window_started_at, count = self._windows.get(key, (now, 0))
        elapsed = now - window_started_at
        if elapsed >= 60:
            window_started_at = now
            count = 0
            elapsed = 0

        if count >= limit:
            retry_after = max(1, int(60 - elapsed))
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        "rate limit exceeded; retry after "
                        f"{retry_after} seconds"
                    )
                },
                headers={"Retry-After": str(retry_after)},
            )

        self._windows[key] = (window_started_at, count + 1)
        return await call_next(request)

    def _request_key(self, request: Request) -> str:
        session_token = request.cookies.get("logan_session")
        if session_token:
            return f"session:{hash_token(session_token)}"
        client_host = request.client.host if request.client else "unknown"
        return f"ip:{client_host}"
