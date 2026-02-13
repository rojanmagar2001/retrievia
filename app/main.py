from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.logging import configure_logging, get_logger

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


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["system"])
def readyz() -> dict[str, str]:
    return {"status": "ready"}
