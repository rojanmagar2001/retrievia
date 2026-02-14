from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from app.ingestion.types import ParsedSection


def parse_pdf(file_path: str) -> list[ParsedSection]:
    reader = PdfReader(file_path)
    sections: list[ParsedSection] = []

    for page_idx, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        sections.append(ParsedSection(text=text, page=page_idx, section=f"page-{page_idx}"))

    if sections:
        return sections

    name = Path(file_path).name
    raise ValueError(f"No extractable text found in PDF: {name}")
