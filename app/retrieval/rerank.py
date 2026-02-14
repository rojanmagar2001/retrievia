from __future__ import annotations

from typing import Protocol

from app.retrieval.types import CandidateChunk


class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[CandidateChunk], top_k: int) -> list[CandidateChunk]: ...


class NoopReranker:
    def rerank(self, query: str, candidates: list[CandidateChunk], top_k: int) -> list[CandidateChunk]:
        del query
        return candidates[:top_k]
