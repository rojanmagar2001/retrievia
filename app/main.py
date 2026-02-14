from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.testing import router as testing_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_size import RequestSizeLimitMiddleware
from app.middleware.tenant_context import TenantContextMiddleware

configure_logging(level=settings.log_level, json_logs=settings.log_json)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "startup_complete",
        app_name=settings.app_name,
        app_env=settings.app_env,
        log_level=settings.log_level,
    )
    yield
    logger.info("shutdown_complete")

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(TenantContextMiddleware)
app.add_middleware(RequestSizeLimitMiddleware, max_body_bytes=settings.request_max_body_bytes)
app.add_middleware(RateLimitMiddleware)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(testing_router)


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["system"])
def readyz() -> dict[str, str]:
    return {"status": "ready"}
