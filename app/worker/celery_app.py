from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "retrievia",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(name="health.ping")
def ping() -> str:
    return "pong"
