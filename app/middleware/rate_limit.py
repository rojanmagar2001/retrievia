from __future__ import annotations

import time

from fastapi.responses import JSONResponse
from redis import Redis

from app.core.config import settings
from app.core.logging import get_logger
from app.security.jwt import TokenError, decode_access_token

logger = get_logger(__name__)


class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in {"/healthz", "/readyz", "/metrics"}:
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        identifier = self._identity(scope, headers)

        window_seconds = settings.rate_limit_window_seconds
        window = int(time.time() // window_seconds)
        key = f"ratelimit:{identifier}:{window}"

        try:
            pipe = self.redis.pipeline()
            pipe.incr(key, 1)
            pipe.expire(key, window_seconds + 1)
            current, _ = pipe.execute()
        except Exception:
            logger.warning("rate_limit_redis_unavailable", path=path)
            await self.app(scope, receive, send)
            return

        if int(current) > settings.rate_limit_requests:
            retry_after = window_seconds - (int(time.time()) % window_seconds)
            response = JSONResponse(
                status_code=429,
                content={"detail": "rate_limit_exceeded"},
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _identity(self, scope, headers: dict[str, str]) -> str:
        auth_header = headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            try:
                payload = decode_access_token(token)
                return f"tenant:{payload['tenant_id']}:user:{payload['sub']}"
            except TokenError:
                pass

        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        return f"ip:{client_ip}"
