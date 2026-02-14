from __future__ import annotations

from app.ingestion.types import ChunkPayload, ParsedSection


class TextChunker:
    def __init__(self, chunk_size: int, overlap: int) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than 0")
        if overlap < 0:
            raise ValueError("overlap cannot be negative")
        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")

        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(
        self,
        sections: list[ParsedSection],
        base_metadata: dict,
    ) -> list[ChunkPayload]:
        chunks: list[ChunkPayload] = []
        chunk_index = 0

        for section in sections:
            text = section.text.strip()
            if not text:
                continue

            start = 0
            while start < len(text):
                end = min(start + self.chunk_size, len(text))
                chunk_text = text[start:end].strip()
                if chunk_text:
                    metadata = dict(base_metadata)
                    metadata.update(
                        {
                            "page": section.page,
                            "section": section.section,
                            "char_start": start,
                            "char_end": end,
                        }
                    )
                    chunks.append(
                        ChunkPayload(
                            chunk_index=chunk_index,
                            content_text=chunk_text,
                            page_number=section.page,
                            section=section.section,
                            token_count=_estimate_token_count(chunk_text),
                            metadata=metadata,
                        )
                    )
                    chunk_index += 1

                if end >= len(text):
                    break
                start = end - self.overlap

        return chunks


def _estimate_token_count(text: str) -> int:
    return max(1, len(text.split()))
