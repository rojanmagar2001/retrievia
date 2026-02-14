from __future__ import annotations

from fastapi.responses import JSONResponse


class RequestSizeLimitMiddleware:
    def __init__(self, app, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_body_bytes:
                    response = JSONResponse(status_code=413, content={"detail": "request_entity_too_large"})
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass

        body_size = 0

        async def limited_receive():
            nonlocal body_size
            message = await receive()
            if message["type"] == "http.request":
                body_size += len(message.get("body", b""))
                if body_size > self.max_body_bytes:
                    raise ValueError("request_too_large")
            return message

        try:
            await self.app(scope, limited_receive, send)
        except ValueError as exc:
            if str(exc) != "request_too_large":
                raise
            response = JSONResponse(status_code=413, content={"detail": "request_entity_too_large"})
            await response(scope, receive, send)
