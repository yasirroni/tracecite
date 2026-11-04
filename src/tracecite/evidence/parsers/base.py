"""Parser interface: authoritative files in, retained pages + logical chunk
input units out. Chunking (chunking.py) turns ``ParsedChunkUnit`` sequences
into stored chunks; parsers never write to the database directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedPage:
    """One retained extraction container, such as a page or worksheet."""

    physical_page: int
    printed_label: str | None
    text: str
    extraction_method: str
    extraction_status: str
    section_candidates: list[str] = field(default_factory=list)
    layout: dict | None = None


@dataclass(frozen=True)
class ParsedChunkUnit:
    """One chunkable unit of text with enough locator context to build a
    stable logical key and, later, a semantic-input hash.
    """

    text: str
    logical_key: str
    heading_path: list[str]
    symbol: str | None
    content_type: str
    physical_page: int | None = None
    page_start_offset: int | None = None
    page_end_offset: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    locator: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ParseResult:
    pages: list[ParsedPage]
    units: list[ParsedChunkUnit]


def units_from_layout(layout_json: str | None) -> list[ParsedChunkUnit]:
    """Rebuild Markdown or workbook chunk-input units from retained ``pages.layout_json``."""
    layout = json.loads(layout_json) if layout_json else {}
    return [
        ParsedChunkUnit(
            text=entry["text"],
            logical_key=entry["logical_key"],
            heading_path=entry["heading_path"],
            symbol=None,
            content_type=entry["content_type"],
            line_start=entry.get("line_start"),
            line_end=entry.get("line_end"),
            locator=entry.get("locator", {}),
        )
        for entry in layout.get("units", [])
    ]
