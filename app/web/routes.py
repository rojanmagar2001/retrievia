from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
import redis.asyncio as redis
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.db.models import Conversation, User
from app.db.session import SessionLocal
from app.security.jwt import TokenError, decode_access_token

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(include_in_schema=False)

_redis_client: redis.Redis | None = None
LAST_TENANT_COOKIE_NAME = "retrievia_last_tenant"


@dataclass(slots=True)
class WebAuthContext:
    session_id: str
    token: str
    tenant_id: str


@dataclass(slots=True)
class TenantResolution:
    tenant_id: str | None
    reason: str


def _resolve_tenant_for_login(email: str, tenant_hint: str) -> TenantResolution:
    explicit_tenant = tenant_hint.strip()
    if explicit_tenant:
        return TenantResolution(tenant_id=explicit_tenant, reason="provided")

    normalized_email = email.strip().lower()
    if not normalized_email:
        return TenantResolution(tenant_id=None, reason="email_missing")

    with SessionLocal() as db:
        tenant_ids = db.scalars(
            select(User.tenant_id)
            .where(func.lower(User.email) == normalized_email)
            .distinct()
        ).all()

    if len(tenant_ids) == 1:
        return TenantResolution(tenant_id=str(tenant_ids[0]), reason="inferred")
    if len(tenant_ids) > 1:
        return TenantResolution(tenant_id=None, reason="ambiguous")
    return TenantResolution(tenant_id=None, reason="not_found")


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def _extract_error_detail(status_code: int, payload: dict[str, Any] | None) -> str:
    detail = payload.get("detail") if payload else None
    if isinstance(detail, str) and detail:
        return detail
    return f"request_failed_{status_code}"


def _redirect_login_response(request: Request) -> Response:
    if _is_htmx(request):
        return Response(status_code=401, headers={"HX-Redirect": "/login"})
    return RedirectResponse(url="/login", status_code=303)


def _template_context(request: Request, **extra: Any) -> dict[str, Any]:
    auth = getattr(request.state, "web_auth", None)
    base_context: dict[str, Any] = {
        "request": request,
        "active_tenant_id": (auth.tenant_id if isinstance(auth, WebAuthContext) else None),
        "current_path": request.url.path,
    }
    base_context.update(extra)
    return base_context


def _backend_headers(token: str, tenant_id: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": tenant_id,
    }
    if extra:
        headers.update(extra)
    return headers


def _can_retry_chat_without_conversation(
    *,
    status_code: int,
    payload: dict[str, Any],
    response_body: dict[str, Any] | None,
    response_text: str,
) -> bool:
    if not payload.get("conversation_id"):
        return False

    detail = ""
    if response_body and isinstance(response_body.get("detail"), str):
        detail = response_body["detail"]
    haystack = f"{detail} {response_text}".lower()

    if status_code in {404, 422} and "conversation" in haystack:
        return True
    if "fk_messages_conversation_id_conversations" in haystack:
        return True
    if "foreignkeyviolation" in haystack and "conversation_id" in haystack:
        return True
    return False


def _sanitize_conversation_id_for_auth(
    *,
    conversation_id_raw: str | None,
    auth: WebAuthContext,
) -> str | None:
    if not conversation_id_raw:
        return None

    try:
        conversation_id = UUID(conversation_id_raw)
        tenant_id = UUID(auth.tenant_id)
    except ValueError:
        return None

    user_id: UUID | None = None
    try:
        token_payload = decode_access_token(auth.token)
        user_id_raw = token_payload.get("sub")
        if isinstance(user_id_raw, str):
            user_id = UUID(user_id_raw)
    except (TokenError, ValueError):
        user_id = None

    with SessionLocal() as db:
        stmt = select(Conversation.id).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
        if user_id is not None:
            stmt = stmt.where(or_(Conversation.user_id.is_(None), Conversation.user_id == user_id))
        existing = db.scalar(stmt)

    return str(existing) if existing is not None else None


def _cookie_kwargs() -> dict[str, Any]:
    return {
        "httponly": True,
        "secure": settings.web_cookie_secure,
        "samesite": "lax",
        "max_age": settings.web_session_ttl_seconds,
        "path": "/",
    }


async def _redis_conn() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    return _redis_client


def _session_key(session_id: str) -> str:
    return f"web:session:{session_id}"


async def _save_session(*, token: str, tenant_id: str) -> str:
    session_id = secrets.token_urlsafe(32)
    payload = json.dumps({"token": token, "tenant_id": tenant_id}, separators=(",", ":"))
    conn = await _redis_conn()
    await conn.setex(_session_key(session_id), settings.web_session_ttl_seconds, payload)
    return session_id


async def _load_session(session_id: str) -> WebAuthContext | None:
    conn = await _redis_conn()
    raw = await conn.get(_session_key(session_id))
    if raw is None:
        return None

    try:
        payload_raw = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload_raw, dict):
        return None

    token = payload_raw.get("token")
    tenant_id = payload_raw.get("tenant_id")
    if not isinstance(token, str) or not isinstance(tenant_id, str):
        return None

    await conn.expire(_session_key(session_id), settings.web_session_ttl_seconds)
    return WebAuthContext(session_id=session_id, token=token, tenant_id=tenant_id)


async def _clear_session(session_id: str | None) -> None:
    if not session_id:
        return
    conn = await _redis_conn()
    await conn.delete(_session_key(session_id))


class WebSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/app"):
            session_id = request.cookies.get(settings.web_session_cookie_name)
            if not session_id:
                return _redirect_login_response(request)

            auth_ctx = await _load_session(session_id)
            if auth_ctx is None:
                response = _redirect_login_response(request)
                response.delete_cookie(settings.web_session_cookie_name, path="/")
                return response
            request.state.web_auth = auth_ctx

        return await call_next(request)


def _get_auth(request: Request) -> WebAuthContext:
    auth = getattr(request.state, "web_auth", None)
    if not isinstance(auth, WebAuthContext):
        raise RuntimeError("missing_web_auth_context")
    return auth


@router.get("/")
async def web_root(request: Request) -> Response:
    if request.cookies.get(settings.web_session_cookie_name):
        return RedirectResponse(url="/app/chat", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "auth/register.html",
        _template_context(request, form_values={}, form_error=None),
    )


@router.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    full_name: str = Form(default=""),
    email: str = Form(...),
    password: str = Form(...),
    tenant_id: str = Form(...),
) -> Response:
    payload = {
        "email": email.strip(),
        "password": password,
        "full_name": (full_name.strip() or None),
    }
    form_values = {
        "full_name": full_name,
        "email": email,
        "tenant_id": tenant_id,
    }

    async with httpx.AsyncClient(base_url=settings.web_backend_base_url, timeout=30.0) as client:
        api_response = await client.post(
            "/auth/register",
            headers={
                "X-Tenant-Id": tenant_id.strip(),
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if api_response.status_code == 201:
        if _is_htmx(request):
            response = Response(status_code=204, headers={"HX-Redirect": "/login"})
        else:
            response = RedirectResponse(url="/login", status_code=303)
        response.set_cookie(
            LAST_TENANT_COOKIE_NAME,
            tenant_id.strip(),
            httponly=True,
            secure=settings.web_cookie_secure,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,
            path="/",
        )
        return response

    body: dict[str, Any] | None = None
    try:
        body = api_response.json()
    except ValueError:
        body = None

    error_message = _extract_error_detail(api_response.status_code, body)
    return templates.TemplateResponse(
        "partials/auth_register_form.html" if _is_htmx(request) else "auth/register.html",
        _template_context(request, form_values=form_values, form_error=error_message),
        status_code=api_response.status_code,
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    tenant_hint = request.cookies.get(LAST_TENANT_COOKIE_NAME, "")
    return templates.TemplateResponse(
        "auth/login.html",
        _template_context(request, form_values={"tenant_id": tenant_hint}, form_error=None),
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    tenant_id: str = Form(default=""),
) -> Response:
    cookie_tenant_id = request.cookies.get(LAST_TENANT_COOKIE_NAME) or ""
    tenant_resolution = _resolve_tenant_for_login(email, tenant_id.strip() or cookie_tenant_id.strip())
    resolved_tenant_id = tenant_resolution.tenant_id or ""
    form_values = {
        "email": email,
        "tenant_id": resolved_tenant_id,
    }

    if not resolved_tenant_id:
        error_message = "tenant_not_found_for_email"
        if tenant_resolution.reason == "ambiguous":
            error_message = "multiple_tenants_for_email_use_manual_tenant_once"
        return templates.TemplateResponse(
            "partials/auth_login_form.html" if _is_htmx(request) else "auth/login.html",
            _template_context(
                request,
                form_values=form_values,
                form_error=error_message,
            ),
            status_code=400,
        )

    async with httpx.AsyncClient(base_url=settings.web_backend_base_url, timeout=30.0) as client:
        api_response = await client.post(
            "/auth/login",
            headers={
                "X-Tenant-Id": resolved_tenant_id,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"username": email.strip(), "password": password},
        )

    if api_response.status_code == 200:
        body_raw = api_response.json()
        access_token = (
            body_raw.get("access_token")
            if isinstance(body_raw, dict)
            else None
        )
        if not isinstance(access_token, str) or not access_token:
            return templates.TemplateResponse(
                "partials/auth_login_form.html" if _is_htmx(request) else "auth/login.html",
                _template_context(
                    request,
                    form_values=form_values,
                    form_error="invalid_login_response",
                ),
                status_code=502,
            )

        session_id = await _save_session(token=access_token, tenant_id=resolved_tenant_id)
        if _is_htmx(request):
            response = Response(status_code=204, headers={"HX-Redirect": "/app/chat"})
        else:
            response = RedirectResponse(url="/app/chat", status_code=303)
        response.set_cookie(settings.web_session_cookie_name, session_id, **_cookie_kwargs())
        response.set_cookie(
            LAST_TENANT_COOKIE_NAME,
            resolved_tenant_id,
            httponly=True,
            secure=settings.web_cookie_secure,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,
            path="/",
        )
        return response

    body: dict[str, Any] | None = None
    try:
        body = api_response.json()
    except ValueError:
        body = None

    error_message = _extract_error_detail(api_response.status_code, body)
    return templates.TemplateResponse(
        "partials/auth_login_form.html" if _is_htmx(request) else "auth/login.html",
        _template_context(request, form_values=form_values, form_error=error_message),
        status_code=api_response.status_code,
    )


@router.get("/logout")
async def logout(request: Request) -> Response:
    session_id = request.cookies.get(settings.web_session_cookie_name)
    await _clear_session(session_id)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(settings.web_session_cookie_name, path="/")
    return response


@router.get("/app", response_class=HTMLResponse)
async def app_root() -> Response:
    return RedirectResponse(url="/app/chat", status_code=303)


@router.get("/app/chat", response_class=HTMLResponse)
async def app_chat_page(request: Request) -> HTMLResponse:
    auth = _get_auth(request)
    conversation_items: list[dict[str, str]] = []

    async with httpx.AsyncClient(base_url=settings.web_backend_base_url, timeout=30.0) as client:
        seeded = await client.get(
            "/v1/chat/conversations",
            headers=_backend_headers(auth.token, auth.tenant_id),
        )
        if seeded.status_code == 200:
            data = seeded.json()
            for item in data.get("items", []):
                if item.get("conversation_id"):
                    conversation_items.append(
                        {
                            "conversation_id": item["conversation_id"],
                            "title": item.get("title") or "Conversation",
                        }
                    )

    return templates.TemplateResponse(
        "app/chat.html",
        _template_context(
            request,
            page_title="Chat",
            conversation_items=conversation_items,
            toast_message=None,
        ),
    )


@router.post("/app/chat/send", response_class=HTMLResponse)
async def app_chat_send(
    request: Request,
    message: str = Form(...),
    conversation_id: str = Form(default=""),
    mode: str = Form(default="sync"),
) -> HTMLResponse:
    auth = _get_auth(request)
    conversation_value = _sanitize_conversation_id_for_auth(
        conversation_id_raw=(conversation_id.strip() or None),
        auth=auth,
    )
    payload: dict[str, Any] = {"message": message.strip()}
    if conversation_value:
        payload["conversation_id"] = conversation_value

    if mode == "stream":
        return templates.TemplateResponse(
            "partials/chat_stream_prepare.html",
            _template_context(
                request,
                user_message=message.strip(),
                conversation_id=conversation_value,
            ),
        )

    response_body: dict[str, Any] | None = None
    response_text = ""
    async with httpx.AsyncClient(base_url=settings.web_backend_base_url, timeout=90.0) as client:
        api_response = await client.post(
            "/v1/chat",
            headers=_backend_headers(
                auth.token,
                auth.tenant_id,
                {"Content-Type": "application/json"},
            ),
            json=payload,
        )

        if api_response.status_code != 200:
            try:
                response_body = api_response.json()
            except ValueError:
                response_body = None
            response_text = api_response.text

            if _can_retry_chat_without_conversation(
                status_code=api_response.status_code,
                payload=payload,
                response_body=response_body,
                response_text=response_text,
            ):
                payload_no_conversation = {"message": payload["message"]}
                api_response = await client.post(
                    "/v1/chat",
                    headers=_backend_headers(
                        auth.token,
                        auth.tenant_id,
                        {"Content-Type": "application/json"},
                    ),
                    json=payload_no_conversation,
                )
                if api_response.status_code == 200:
                    conversation_value = None

    if api_response.status_code != 200:
        error_text = "chat_request_failed"
        if response_body is None:
            try:
                response_body = api_response.json()
            except ValueError:
                response_body = None
        error_text = _extract_error_detail(api_response.status_code, response_body)
        return templates.TemplateResponse(
            "partials/chat_error.html",
            _template_context(request, error_message=error_text),
            status_code=api_response.status_code,
        )

    body = api_response.json()
    response_conversation_id = str(body.get("conversation_id") or "").strip()
    if response_conversation_id:
        conversation_value = response_conversation_id
    return templates.TemplateResponse(
        "partials/chat_exchange.html",
        _template_context(
            request,
            user_message=message.strip(),
            conversation_id=conversation_value,
            answer=body.get("answer", ""),
            citations=body.get("citations", []),
            sources=body.get("sources", []),
        ),
    )


@router.post("/app/chat/stream")
async def app_chat_stream(request: Request) -> StreamingResponse:
    auth = _get_auth(request)
    payload_raw = await request.json()
    payload_message = str(payload_raw.get("message") or "").strip()
    payload: dict[str, Any] = {"message": payload_message}
    sanitized_conversation_id = _sanitize_conversation_id_for_auth(
        conversation_id_raw=(str(payload_raw.get("conversation_id") or "").strip() or None),
        auth=auth,
    )
    if sanitized_conversation_id:
        payload["conversation_id"] = sanitized_conversation_id

    async def _forward_stream():
        current_payload: dict[str, Any] = dict(payload)
        retried_without_conversation = False
        async with httpx.AsyncClient(base_url=settings.web_backend_base_url, timeout=120.0) as client:
            while True:
                async with client.stream(
                    "POST",
                    "/v1/chat/stream",
                    headers=_backend_headers(
                        auth.token,
                        auth.tenant_id,
                        {
                            "Accept": "text/event-stream",
                            "Content-Type": "application/json",
                        },
                    ),
                    json=current_payload,
                ) as api_response:
                    if api_response.status_code != 200:
                        details = await api_response.aread()
                        message = details.decode("utf-8", errors="ignore") or "stream_request_failed"

                        response_body: dict[str, Any] | None = None
                        try:
                            parsed = json.loads(message)
                            if isinstance(parsed, dict):
                                response_body = parsed
                        except json.JSONDecodeError:
                            response_body = None

                        can_retry = (not retried_without_conversation) and _can_retry_chat_without_conversation(
                            status_code=api_response.status_code,
                            payload=current_payload,
                            response_body=response_body,
                            response_text=message,
                        )
                        if can_retry:
                            retried_without_conversation = True
                            current_payload = {"message": str(current_payload.get("message", ""))}
                            continue

                        yield f"event: error\ndata: {json.dumps({'message': message})}\n\n"
                        return

                    async for chunk in api_response.aiter_text():
                        if chunk:
                            yield chunk
                    return

    return StreamingResponse(
        _forward_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/app/chat/conversations/{conversation_id}", response_class=HTMLResponse)
async def app_chat_conversation_history(request: Request, conversation_id: str) -> HTMLResponse:
    auth = _get_auth(request)
    conversation_id_value = str(_sanitize_conversation_id_for_auth(conversation_id_raw=conversation_id, auth=auth) or "")
    if not conversation_id_value:
        return templates.TemplateResponse(
            "partials/chat_error.html",
            _template_context(request, error_message="conversation_not_found"),
            status_code=404,
        )

    async with httpx.AsyncClient(base_url=settings.web_backend_base_url, timeout=30.0) as client:
        api_response = await client.get(
            f"/v1/chat/conversations/{conversation_id_value}",
            headers=_backend_headers(auth.token, auth.tenant_id),
        )

    if api_response.status_code != 200:
        body: dict[str, Any] | None = None
        try:
            body = api_response.json()
        except ValueError:
            body = None
        return templates.TemplateResponse(
            "partials/chat_error.html",
            _template_context(request, error_message=_extract_error_detail(api_response.status_code, body)),
            status_code=api_response.status_code,
        )

    data = api_response.json()
    messages = data.get("items", []) if isinstance(data, dict) else []
    latest_sources: list[dict[str, Any]] = []
    for item in reversed(messages):
        if item.get("role") != "assistant":
            continue
        citations = item.get("citations")
        if not isinstance(citations, list):
            continue
        latest_sources = [
            {
                "citation_id": str(citation.get("id") or ""),
                "chunk_id": "",
                "doc_id": str(citation.get("doc_id") or ""),
                "title": str(citation.get("title") or "Untitled"),
                "page": citation.get("page"),
                "section": citation.get("section"),
                "score": 0,
            }
            for citation in citations
            if isinstance(citation, dict) and citation.get("id")
        ]
        break

    return templates.TemplateResponse(
        "partials/chat_history.html",
        _template_context(
            request,
            conversation_id=conversation_id_value,
            conversation_title=str(data.get("title") or "New chat"),
            messages=messages,
            latest_sources=latest_sources,
        ),
    )


@router.patch("/app/chat/conversations/{conversation_id}")
async def app_chat_conversation_rename(request: Request, conversation_id: str) -> Response:
    auth = _get_auth(request)
    conversation_id_value = str(_sanitize_conversation_id_for_auth(conversation_id_raw=conversation_id, auth=auth) or "")
    if not conversation_id_value:
        return Response(status_code=404)

    body_raw = await request.json()
    title = str(body_raw.get("title") or "").strip()
    if not title:
        return Response(content=json.dumps({"detail": "title_required"}), media_type="application/json", status_code=422)

    async with httpx.AsyncClient(base_url=settings.web_backend_base_url, timeout=30.0) as client:
        api_response = await client.patch(
            f"/v1/chat/conversations/{conversation_id_value}",
            headers=_backend_headers(
                auth.token,
                auth.tenant_id,
                {"Content-Type": "application/json"},
            ),
            json={"title": title},
        )

    return Response(
        content=api_response.text,
        status_code=api_response.status_code,
        media_type=(api_response.headers.get("content-type") or "application/json"),
    )


@router.delete("/app/chat/conversations/{conversation_id}")
async def app_chat_conversation_delete(request: Request, conversation_id: str) -> Response:
    auth = _get_auth(request)
    conversation_id_value = str(_sanitize_conversation_id_for_auth(conversation_id_raw=conversation_id, auth=auth) or "")
    if not conversation_id_value:
        return Response(status_code=404)

    async with httpx.AsyncClient(base_url=settings.web_backend_base_url, timeout=30.0) as client:
        api_response = await client.delete(
            f"/v1/chat/conversations/{conversation_id_value}",
            headers=_backend_headers(auth.token, auth.tenant_id),
        )

    return Response(status_code=api_response.status_code)


@router.get("/app/documents", response_class=HTMLResponse)
async def app_documents_page(request: Request) -> HTMLResponse:
    auth = _get_auth(request)
    async with httpx.AsyncClient(base_url=settings.web_backend_base_url, timeout=30.0) as client:
        api_response = await client.get(
            "/v1/documents",
            headers=_backend_headers(auth.token, auth.tenant_id),
        )
    documents = api_response.json() if api_response.status_code == 200 else []
    return templates.TemplateResponse(
        "app/documents.html",
        _template_context(request, page_title="Documents", documents=documents, toast_message=None),
    )


@router.get("/app/documents/list", response_class=HTMLResponse)
async def app_documents_list_partial(request: Request) -> HTMLResponse:
    auth = _get_auth(request)
    async with httpx.AsyncClient(base_url=settings.web_backend_base_url, timeout=30.0) as client:
        api_response = await client.get(
            "/v1/documents",
            headers=_backend_headers(auth.token, auth.tenant_id),
        )
    documents = api_response.json() if api_response.status_code == 200 else []
    return templates.TemplateResponse(
        "partials/document_rows.html",
        _template_context(request, documents=documents),
    )


@router.post("/app/documents/upload", response_class=HTMLResponse)
async def app_documents_upload(
    request: Request,
    title: str = Form(default=""),
    external_id: str = Form(default=""),
    file: UploadFile = File(...),
) -> HTMLResponse:
    auth = _get_auth(request)
    file_bytes = await file.read()
    document_id: str | None = None
    ingestion_job_id: str | None = None

    async with httpx.AsyncClient(base_url=settings.web_backend_base_url, timeout=120.0) as client:
        upload_response = await client.post(
            "/v1/documents/upload",
            headers=_backend_headers(auth.token, auth.tenant_id),
            data={"title": title, "external_id": external_id},
            files={"file": (file.filename, file_bytes, file.content_type or "application/octet-stream")},
        )

        if upload_response.status_code in {200, 201}:
            upload_body = upload_response.json()
            document_id = upload_body.get("document", {}).get("document_id")
            ingestion_job_id = upload_body.get("ingestion", {}).get("ingestion_job_id")
            if document_id:
                ingest_response = await client.post(
                    f"/v1/documents/{document_id}/ingest",
                    headers=_backend_headers(auth.token, auth.tenant_id),
                )
                if ingest_response.status_code == 200:
                    ingestion_job_id = ingest_response.json().get("ingestion_job_id") or ingestion_job_id
        else:
            body: dict[str, Any] | None = None
            try:
                body = upload_response.json()
            except ValueError:
                body = None
            return templates.TemplateResponse(
                "partials/toast.html",
                _template_context(
                    request,
                    toast_level="error",
                    toast_message=_extract_error_detail(upload_response.status_code, body),
                ),
                status_code=upload_response.status_code,
            )

        list_response = await client.get(
            "/v1/documents",
            headers=_backend_headers(auth.token, auth.tenant_id),
        )

    documents = list_response.json() if list_response.status_code == 200 else []
    return templates.TemplateResponse(
        "partials/document_upload_result.html",
        _template_context(
            request,
            documents=documents,
            ingestion_job_id=ingestion_job_id,
            toast_message=("Document uploaded and ingestion queued" if document_id else "Upload completed"),
        ),
    )


@router.get("/app/documents/{document_id}", response_class=HTMLResponse)
async def app_document_detail(request: Request, document_id: str) -> HTMLResponse:
    auth = _get_auth(request)
    async with httpx.AsyncClient(base_url=settings.web_backend_base_url, timeout=30.0) as client:
        api_response = await client.get(
            f"/v1/documents/{document_id}",
            headers=_backend_headers(auth.token, auth.tenant_id),
        )

    if api_response.status_code != 200:
        return templates.TemplateResponse(
            "partials/toast.html",
            _template_context(request, toast_level="error", toast_message="document_not_found"),
            status_code=api_response.status_code,
        )

    return templates.TemplateResponse(
        "partials/document_detail.html",
        _template_context(request, document=api_response.json()),
    )


@router.get("/app/ingestion-jobs/{job_id}", response_class=HTMLResponse)
async def app_ingestion_job_status(request: Request, job_id: str) -> HTMLResponse:
    auth = _get_auth(request)
    async with httpx.AsyncClient(base_url=settings.web_backend_base_url, timeout=30.0) as client:
        api_response = await client.get(
            f"/v1/ingestion-jobs/{job_id}",
            headers=_backend_headers(auth.token, auth.tenant_id),
        )

    if api_response.status_code != 200:
        return templates.TemplateResponse(
            "partials/ingestion_job_status.html",
            _template_context(request, ingestion_job={"status": "unknown", "error_message": "unavailable"}),
        )

    return templates.TemplateResponse(
        "partials/ingestion_job_status.html",
        _template_context(request, ingestion_job=api_response.json()),
    )


@router.get("/app/settings", response_class=HTMLResponse)
async def app_settings_page(request: Request) -> HTMLResponse:
    auth = _get_auth(request)
    async with httpx.AsyncClient(base_url=settings.web_backend_base_url, timeout=30.0) as client:
        api_response = await client.get(
            "/auth/me",
            headers=_backend_headers(auth.token, auth.tenant_id),
        )
    me_data = api_response.json() if api_response.status_code == 200 else None
    return templates.TemplateResponse(
        "app/settings.html",
        _template_context(request, page_title="Settings", me_data=me_data),
    )
