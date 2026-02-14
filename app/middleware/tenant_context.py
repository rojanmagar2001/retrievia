from __future__ import annotations

from uuid import UUID

from app.db.session import reset_current_tenant_id, set_current_tenant_id
from app.security.jwt import TokenError, decode_access_token


class TenantContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = None
        for raw_name, raw_value in scope.get("headers", []):
            if raw_name.decode("latin-1").lower() == "authorization":
                value = raw_value.decode("latin-1")
                if value.startswith("Bearer "):
                    token = value.split(" ", 1)[1]
                break

        tenant_token = None
        if token:
            try:
                payload = decode_access_token(token)
                tenant_token = set_current_tenant_id(UUID(payload["tenant_id"]))
            except (TokenError, ValueError):
                tenant_token = None

        try:
            await self.app(scope, receive, send)
        finally:
            if tenant_token is not None:
                reset_current_tenant_id(tenant_token)
