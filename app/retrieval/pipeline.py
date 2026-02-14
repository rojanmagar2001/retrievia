from __future__ import annotations

from collections.abc import Iterable
from math import sqrt
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Chunk
from app.db.session import reset_current_tenant_id, set_current_tenant_id
from app.providers.llm.gemini import GeminiProvider
from app.retrieval.rerank import NoopReranker, Reranker
from app.retrieval.types import CandidateChunk, RetrievalItem, RetrievalResult
from app.stores.vector.pinecone_store import PineconeVectorStore


class RetrievalPipeline:
    def __init__(
        self,
        db: Session,
        embedder: GeminiProvider | None = None,
        vector_store: PineconeVectorStore | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.db = db
        self.embedder = embedder or GeminiProvider()
        self.vector_store = vector_store or PineconeVectorStore()
        self.reranker = reranker or NoopReranker()

    def retrieve(
        self,
        *,
        tenant_id: UUID,
        query: str,
        top_k: int | None = None,
        doc_ids: list[UUID] | None = None,
        use_mmr: bool | None = None,
        rerank_enabled: bool | None = None,
    ) -> RetrievalResult:
        resolved_top_k = top_k or settings.retrieval_top_k
        resolved_use_mmr = settings.retrieval_use_mmr if use_mmr is None else use_mmr
        resolved_rerank_enabled = (
            settings.retrieval_rerank_enabled if rerank_enabled is None else rerank_enabled
        )

        query_embedding = self.embedder.embed([query])[0]
        pinecone_result = self.vector_store.query(
            tenant_id=str(tenant_id),
            vector=query_embedding,
            top_k=max(resolved_top_k, settings.retrieval_fetch_k),
            doc_ids=[str(doc_id) for doc_id in doc_ids] if doc_ids else None,
            include_values=resolved_use_mmr,
            include_metadata=True,
        )

        candidates = _to_candidates(getattr(pinecone_result, "matches", []) or [])
        deduped = _dedup_candidates(candidates)

        selected: list[CandidateChunk]
        if resolved_use_mmr:
            selected = _mmr_select(
                query_embedding=query_embedding,
                candidates=deduped,
                top_k=resolved_top_k,
                lambda_mult=settings.retrieval_mmr_lambda,
            )
        else:
            selected = deduped[:resolved_top_k]

        if resolved_rerank_enabled:
            selected = self.reranker.rerank(query=query, candidates=selected, top_k=resolved_top_k)

        vector_ids = [candidate.vector_id for candidate in selected]
        chunk_rows = self._load_chunks(tenant_id=tenant_id, vector_ids=vector_ids)

        items: list[RetrievalItem] = []
        debug_scores: list[float] = []
        debug_chunk_ids: list[str] = []
        debug_doc_ids: list[str] = []

        for idx, candidate in enumerate(selected):
            chunk = chunk_rows.get(candidate.vector_id)
            if chunk is None:
                continue

            citation_id = str(idx + 1)
            item = RetrievalItem(
                citation_id=citation_id,
                citation_tag=f"[{citation_id}]",
                chunk_id=str(chunk.id),
                doc_id=str(chunk.document_id),
                score=float(candidate.score),
                content=chunk.content_text,
                page=chunk.page_number,
                section=chunk.section,
                metadata=chunk.metadata_json or {},
            )
            items.append(item)
            debug_scores.append(float(candidate.score))
            debug_chunk_ids.append(str(chunk.id))
            debug_doc_ids.append(str(chunk.document_id))

        retrieval_debug = {
            "query": query,
            "top_k": resolved_top_k,
            "fetched": len(candidates),
            "selected": len(items),
            "used_mmr": resolved_use_mmr,
            "rerank_enabled": resolved_rerank_enabled,
            "scores": debug_scores,
            "chunk_ids": debug_chunk_ids,
            "doc_ids": debug_doc_ids,
        }

        return RetrievalResult(query=query, items=items, retrieval_debug=retrieval_debug)

    def _load_chunks(self, tenant_id: UUID, vector_ids: list[str]) -> dict[str, Chunk]:
        if not vector_ids:
            return {}

        token = set_current_tenant_id(tenant_id)
        try:
            rows = self.db.scalars(
                select(Chunk).where(
                    Chunk.tenant_id == tenant_id,
                    Chunk.pinecone_vector_id.in_(vector_ids),
                )
            ).all()
        finally:
            reset_current_tenant_id(token)

        return {
            row.pinecone_vector_id: row
            for row in rows
            if row.pinecone_vector_id is not None
        }


def _to_candidates(matches: Iterable[object]) -> list[CandidateChunk]:
    candidates: list[CandidateChunk] = []
    for match in matches:
        metadata = getattr(match, "metadata", None) or {}
        values = getattr(match, "values", None) or []
        candidates.append(
            CandidateChunk(
                vector_id=str(getattr(match, "id", "")),
                score=float(getattr(match, "score", 0.0)),
                values=[float(v) for v in values],
                metadata=dict(metadata),
            )
        )
    return candidates


def _dedup_candidates(candidates: list[CandidateChunk]) -> list[CandidateChunk]:
    best_by_vector_id: dict[str, CandidateChunk] = {}
    for candidate in candidates:
        existing = best_by_vector_id.get(candidate.vector_id)
        if existing is None or candidate.score > existing.score:
            best_by_vector_id[candidate.vector_id] = candidate

    deduped = list(best_by_vector_id.values())
    deduped.sort(key=lambda item: item.score, reverse=True)
    return deduped


def _mmr_select(
    *,
    query_embedding: list[float],
    candidates: list[CandidateChunk],
    top_k: int,
    lambda_mult: float,
) -> list[CandidateChunk]:
    if top_k <= 0 or not candidates:
        return []

    working = [candidate for candidate in candidates if candidate.values]
    if not working:
        return candidates[:top_k]

    selected: list[CandidateChunk] = []
    remaining = working.copy()

    while remaining and len(selected) < top_k:
        best_idx = 0
        best_score = float("-inf")

        for idx, candidate in enumerate(remaining):
            relevance = _cosine_similarity(query_embedding, candidate.values)
            if not selected:
                mmr_score = relevance
            else:
                diversity_penalty = max(
                    _cosine_similarity(candidate.values, selected_candidate.values)
                    for selected_candidate in selected
                    if selected_candidate.values
                )
                mmr_score = (lambda_mult * relevance) - ((1.0 - lambda_mult) * diversity_penalty)

            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx

        selected.append(remaining.pop(best_idx))

    if len(selected) < top_k:
        missing = [candidate for candidate in candidates if candidate.vector_id not in {s.vector_id for s in selected}]
        selected.extend(missing[: top_k - len(selected)])

    return selected[:top_k]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (sqrt(norm_a) * sqrt(norm_b))
