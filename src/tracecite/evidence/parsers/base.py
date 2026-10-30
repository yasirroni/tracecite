"""Parser interface: authoritative files in, retained pages + logical chunk
input units out. Chunking (chunking.py) turns ``ParsedChunkUnit`` sequences
into stored chunks; parsers never write to the database directly.
"""

from __future__ import annotations

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
    page_range_start: int | None = None
    page_range_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    locator: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ParseResult:
    pages: list[ParsedPage]
    units: list[ParsedChunkUnit]
