from __future__ import annotations

from uuid import UUID

from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.ingestion.pipeline import ingest_document_pipeline
from app.worker.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="ingestion.ingest_document")
def ingest_document(doc_id: str, source: str) -> dict:
    with SessionLocal() as db:
        result = ingest_document_pipeline(db=db, document_id=UUID(doc_id), source=source)
        logger.info("ingestion_document_complete", result=result)
        return result
