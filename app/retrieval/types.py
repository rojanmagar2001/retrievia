from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CandidateChunk:
    vector_id: str
    score: float
    values: list[float]
    metadata: dict[str, Any]


@dataclass(slots=True)
class RetrievalItem:
    citation_id: str
    citation_tag: str
    chunk_id: str
    doc_id: str
    score: float
    content: str
    page: int | None
    section: str | None
    metadata: dict[str, Any]


@dataclass(slots=True)
class RetrievalResult:
    query: str
    items: list[RetrievalItem]
    retrieval_debug: dict[str, Any]

    def to_prompt_context(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "chunks": [
                {
                    "citation_id": item.citation_id,
                    "citation_tag": item.citation_tag,
                    "chunk_id": item.chunk_id,
                    "doc_id": item.doc_id,
                    "page": item.page,
                    "section": item.section,
                    "content": item.content,
                }
                for item in self.items
            ],
        }
