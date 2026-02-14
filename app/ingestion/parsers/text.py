from __future__ import annotations

import re

from app.ingestion.types import ParsedSection

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$")


def parse_text_or_markdown(file_path: str) -> list[ParsedSection]:
    with open(file_path, encoding="utf-8") as handle:
        raw = handle.read()

    if not raw.strip():
        raise ValueError("Document is empty")

    sections: list[ParsedSection] = []
    current_section = "body"
    buffer: list[str] = []

    for line in raw.splitlines():
        match = _HEADER_RE.match(line.strip())
        if match:
            if buffer:
                text = "\n".join(buffer).strip()
                if text:
                    sections.append(ParsedSection(text=text, section=current_section))
                buffer = []
            current_section = match.group(2).strip()
            continue
        buffer.append(line)

    if buffer:
        text = "\n".join(buffer).strip()
        if text:
            sections.append(ParsedSection(text=text, section=current_section))

    return sections
