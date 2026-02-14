from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ParsedSection:
    text: str
    page: int | None = None
    section: str | None = None


@dataclass(slots=True)
class ChunkPayload:
    chunk_index: int
    content_text: str
    page_number: int | None
    section: str | None
    token_count: int
    metadata: dict
