from __future__ import annotations

import hashlib
import mimetypes
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Chunk, Document, DocumentVersion, IngestionJob, IngestionJobStatus, IngestionSourceType
from app.db.session import reset_current_tenant_id, set_current_tenant_id
from app.ingestion.chunker import TextChunker
from app.ingestion.parsers.pdf import parse_pdf
from app.ingestion.parsers.text import parse_text_or_markdown
from app.ingestion.types import ChunkPayload, ParsedSection
from app.providers.llm.gemini import GeminiProvider
from app.stores.vector.pinecone_store import PineconeVectorStore


def ingest_document_pipeline(db: Session, document_id: uuid.UUID, source: str) -> dict:
    document = db.scalar(select(Document).where(Document.id == document_id))
    if document is None:
        raise ValueError(f"Document not found: {document_id}")

    tenant_token = set_current_tenant_id(document.tenant_id)

    try:
        job = _get_or_create_job(db=db, document=document, source=source)
        _set_job_running(job)
        db.commit()

        try:
            source_path = _resolve_source_path(document=document, source=source)
            sections = _parse_source(source_path)
            version = _get_or_create_document_version(db=db, document=document, source_path=source_path)

            chunker = TextChunker(
                chunk_size=settings.ingestion_chunk_size,
                overlap=settings.ingestion_chunk_overlap,
            )
            base_metadata = {
                "doc_id": str(document.id),
                "version": version.version,
                "document_version_id": str(version.id),
            }
            chunks = chunker.chunk(sections=sections, base_metadata=base_metadata)

            _replace_document_chunks(db=db, document=document, version=version, chunks=chunks)
            _embed_and_upsert_chunks(document=document, version=version, chunks=chunks)

            version.chunk_count = len(chunks)
            job.document_version_id = version.id
            job.total_chunks = len(chunks)
            job.processed_chunks = len(chunks)
            job.status = IngestionJobStatus.COMPLETED
            job.error_message = ""
            job.finished_at = datetime.now(UTC)
            db.commit()

            return {
                "tenant_id": str(document.tenant_id),
                "document_id": str(document.id),
                "document_version_id": str(version.id),
                "chunks": len(chunks),
                "job_id": str(job.id),
                "status": job.status.value,
            }
        except Exception as exc:
            db.rollback()
            failed_job = db.get(IngestionJob, job.id)
            if failed_job is not None:
                failed_job.status = IngestionJobStatus.FAILED
                failed_job.error_message = str(exc)
                failed_job.finished_at = datetime.now(UTC)
                db.commit()
            raise
    finally:
        reset_current_tenant_id(tenant_token)


def _get_or_create_job(db: Session, document: Document, source: str) -> IngestionJob:
    stmt = (
        select(IngestionJob)
        .where(IngestionJob.document_id == document.id)
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )
    existing = db.scalar(stmt)
    if existing is not None:
        return existing

    job = IngestionJob(
        tenant_id=document.tenant_id,
        document_id=document.id,
        status=IngestionJobStatus.QUEUED,
        source_type=_infer_source_type(source),
        source_uri=source,
        total_chunks=0,
        processed_chunks=0,
    )
    db.add(job)
    db.flush()
    return job


def _set_job_running(job: IngestionJob) -> None:
    job.status = IngestionJobStatus.RUNNING
    job.error_message = ""
    job.started_at = datetime.now(UTC)


def _resolve_source_path(document: Document, source: str) -> Path:
    candidate = source.strip() or (document.source_uri or "")
    if not candidate:
        raise ValueError("Ingestion source is required")

    if candidate.startswith(("http://", "https://", "s3://")):
        raise ValueError("Only local file sources are currently supported in this pipeline")

    path = Path(candidate).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")
    if not path.is_file():
        raise ValueError(f"Source path is not a file: {path}")
    return path


def _parse_source(path: Path) -> list[ParsedSection]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(str(path))
    if suffix in {".md", ".markdown", ".txt"}:
        return parse_text_or_markdown(str(path))

    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type == "application/pdf":
        return parse_pdf(str(path))
    if mime_type and mime_type.startswith("text/"):
        return parse_text_or_markdown(str(path))

    raise ValueError(f"Unsupported file type: {path.suffix or path.name}")


def _get_or_create_document_version(db: Session, document: Document, source_path: Path) -> DocumentVersion:
    latest = db.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.version.desc())
        .limit(1)
    )

    current_version_number = 1 if latest is None else latest.version + 1
    with source_path.open("rb") as handle:
        raw_bytes = handle.read()

    mime_type, _ = mimetypes.guess_type(source_path.name)
    version = DocumentVersion(
        tenant_id=document.tenant_id,
        document_id=document.id,
        version=current_version_number,
        content_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        mime_type=mime_type,
        size_bytes=len(raw_bytes),
        chunk_count=0,
        metadata_json={"source": str(source_path)},
    )
    db.add(version)
    db.flush()
    return version


def _replace_document_chunks(
    db: Session,
    document: Document,
    version: DocumentVersion,
    chunks: list[ChunkPayload],
) -> None:
    pinecone_store = PineconeVectorStore()
    pinecone_store.delete_by_doc_id(tenant_id=str(document.tenant_id), doc_id=str(document.id))

    db.query(Chunk).filter(Chunk.document_id == document.id).delete(synchronize_session=False)
    db.flush()

    for chunk in chunks:
        row = Chunk(
            tenant_id=document.tenant_id,
            document_id=document.id,
            document_version_id=version.id,
            chunk_index=chunk.chunk_index,
            page_number=chunk.page_number,
            section=chunk.section,
            token_count=chunk.token_count,
            content_text=chunk.content_text,
            metadata_json=chunk.metadata,
            pinecone_vector_id=_vector_id(document_id=document.id, version=version.version, index=chunk.chunk_index),
        )
        db.add(row)
    db.flush()


def _embed_and_upsert_chunks(document: Document, version: DocumentVersion, chunks: list[ChunkPayload]) -> None:
    if not chunks:
        return

    embedder = GeminiProvider()
    store = PineconeVectorStore()
    tenant_id = str(document.tenant_id)
    doc_id = str(document.id)

    for batch_start in range(0, len(chunks), settings.ingestion_embed_batch_size):
        batch = chunks[batch_start : batch_start + settings.ingestion_embed_batch_size]
        texts = [chunk.content_text for chunk in batch]
        vectors = embedder.embed(texts)

        payload: list[dict] = []
        for chunk, values in zip(batch, vectors, strict=True):
            payload.append(
                {
                    "id": _vector_id(document_id=document.id, version=version.version, index=chunk.chunk_index),
                    "values": values,
                    "metadata": {
                        "tenant_id": tenant_id,
                        "doc_id": doc_id,
                        "version": version.version,
                        "page": chunk.page_number,
                        "section": chunk.section,
                        "chunk_index": chunk.chunk_index,
                        "document_version_id": str(version.id),
                    },
                }
            )

        store.upsert_vectors(tenant_id=tenant_id, doc_id=doc_id, vectors=payload)


def _infer_source_type(source: str) -> IngestionSourceType:
    if source.startswith("s3://"):
        return IngestionSourceType.S3
    if source.startswith(("http://", "https://")):
        return IngestionSourceType.URL
    return IngestionSourceType.UPLOAD


def _vector_id(document_id: uuid.UUID, version: int, index: int) -> str:
    return f"doc-{document_id}-v{version}-c{index}"
