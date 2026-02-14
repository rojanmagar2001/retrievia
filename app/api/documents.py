from __future__ import annotations

import mimetypes
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_tenant, get_current_user, get_tenant_scoped_db
from app.core.config import settings
from app.db.models import (
    Document,
    IngestionJob,
    IngestionJobStatus,
    IngestionSourceType,
    Tenant,
    User,
)
from app.worker.tasks.ingestion import ingest_document

router = APIRouter(prefix="/v1", tags=["documents"])

ALLOWED_UPLOAD_SUFFIXES = {".pdf", ".md", ".markdown", ".txt"}
ALLOWED_UPLOAD_MIME_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
}


class DocumentResponse(BaseModel):
    document_id: str
    tenant_id: str
    title: str | None
    source_uri: str | None
    external_id: str | None
    created_at: str


class IngestionEnqueueResponse(BaseModel):
    ingestion_job_id: str
    task_id: str
    status: str


class UploadAndIngestResponse(BaseModel):
    document: DocumentResponse
    ingestion: IngestionEnqueueResponse


class IngestionJobResponse(BaseModel):
    ingestion_job_id: str
    tenant_id: str
    document_id: str | None
    document_version_id: str | None
    status: str
    source_type: str
    source_uri: str | None
    total_chunks: int
    processed_chunks: int
    error_message: str | None
    started_at: str | None
    finished_at: str | None
    created_at: str


@router.post("/documents/upload", response_model=UploadAndIngestResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    external_id: str | None = Form(default=None),
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
) -> UploadAndIngestResponse:
    suffix = Path(file.filename or "").suffix.lower()
    content_type = (file.content_type or "").lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported_file_type")

    if content_type and content_type not in ALLOWED_UPLOAD_MIME_TYPES:
        guessed_content_type, _ = mimetypes.guess_type(file.filename or "")
        if guessed_content_type not in ALLOWED_UPLOAD_MIME_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported_content_type")

    tenant_dir = Path(settings.local_upload_root) / str(current_tenant.id)
    tenant_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{uuid4().hex}{suffix}"
    stored_path = tenant_dir / stored_filename

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty_file")
    stored_path.write_bytes(raw)

    document = Document(
        tenant_id=current_tenant.id,
        title=(title or file.filename or "Untitled").strip(),
        source_uri=str(stored_path),
        external_id=external_id,
        created_by_user_id=current_user.id,
    )
    db.add(document)
    db.flush()

    ingestion_job = IngestionJob(
        tenant_id=current_tenant.id,
        document_id=document.id,
        requested_by_user_id=current_user.id,
        status=IngestionJobStatus.QUEUED,
        source_type=IngestionSourceType.UPLOAD,
        source_uri=str(stored_path),
        total_chunks=0,
        processed_chunks=0,
    )
    db.add(ingestion_job)
    db.flush()

    task = ingest_document.delay(str(document.id), str(stored_path))
    db.commit()

    return UploadAndIngestResponse(
        document=DocumentResponse(
            document_id=str(document.id),
            tenant_id=str(document.tenant_id),
            title=document.title,
            source_uri=document.source_uri,
            external_id=document.external_id,
            created_at=document.created_at.isoformat(),
        ),
        ingestion=IngestionEnqueueResponse(
            ingestion_job_id=str(ingestion_job.id),
            task_id=str(task.id),
            status=IngestionJobStatus.QUEUED.value,
        ),
    )


@router.post("/documents/{document_id}/ingest", response_model=IngestionEnqueueResponse)
def enqueue_document_ingestion(
    document_id: UUID,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
) -> IngestionEnqueueResponse:
    document = db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == current_tenant.id)
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    if not document.source_uri:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="document_missing_source_uri")

    ingestion_job = IngestionJob(
        tenant_id=current_tenant.id,
        document_id=document.id,
        requested_by_user_id=current_user.id,
        status=IngestionJobStatus.QUEUED,
        source_type=IngestionSourceType.UPLOAD,
        source_uri=document.source_uri,
        total_chunks=0,
        processed_chunks=0,
    )
    db.add(ingestion_job)
    db.flush()

    task = ingest_document.delay(str(document.id), document.source_uri)
    db.commit()

    return IngestionEnqueueResponse(
        ingestion_job_id=str(ingestion_job.id),
        task_id=str(task.id),
        status=IngestionJobStatus.QUEUED.value,
    )


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(
    db: Session = Depends(get_tenant_scoped_db),
    current_tenant: Tenant = Depends(get_current_tenant),
) -> list[DocumentResponse]:
    rows = db.scalars(
        select(Document)
        .where(Document.tenant_id == current_tenant.id, Document.is_deleted.is_(False))
        .order_by(Document.created_at.desc())
    ).all()

    return [
        DocumentResponse(
            document_id=str(row.id),
            tenant_id=str(row.tenant_id),
            title=row.title,
            source_uri=row.source_uri,
            external_id=row.external_id,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: UUID,
    db: Session = Depends(get_tenant_scoped_db),
    current_tenant: Tenant = Depends(get_current_tenant),
) -> DocumentResponse:
    row = db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == current_tenant.id)
    )
    if row is None or row.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")

    return DocumentResponse(
        document_id=str(row.id),
        tenant_id=str(row.tenant_id),
        title=row.title,
        source_uri=row.source_uri,
        external_id=row.external_id,
        created_at=row.created_at.isoformat(),
    )


@router.get("/ingestion-jobs/{job_id}", response_model=IngestionJobResponse)
def get_ingestion_job(
    job_id: UUID,
    db: Session = Depends(get_tenant_scoped_db),
    current_tenant: Tenant = Depends(get_current_tenant),
) -> IngestionJobResponse:
    job = db.scalar(
        select(IngestionJob).where(IngestionJob.id == job_id, IngestionJob.tenant_id == current_tenant.id)
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ingestion_job_not_found")

    return IngestionJobResponse(
        ingestion_job_id=str(job.id),
        tenant_id=str(job.tenant_id),
        document_id=(str(job.document_id) if job.document_id is not None else None),
        document_version_id=(str(job.document_version_id) if job.document_version_id is not None else None),
        status=job.status.value,
        source_type=job.source_type.value,
        source_uri=job.source_uri,
        total_chunks=job.total_chunks,
        processed_chunks=job.processed_chunks,
        error_message=job.error_message,
        started_at=(job.started_at.isoformat() if job.started_at is not None else None),
        finished_at=(job.finished_at.isoformat() if job.finished_at is not None else None),
        created_at=job.created_at.isoformat(),
    )
