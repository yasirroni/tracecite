"""Parser interface: authoritative files in, retained pages + logical chunk
input units out. Chunking (chunking.py) turns ``ParsedChunkUnit`` sequences
into stored chunks; parsers never write to the database directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ParsedPage:
    """One physical page of retained extraction (PDF only)."""

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
class ParsedAsset:
    """One PDF visual derivative candidate; rendering happens separately."""

    physical_page: int
    asset_type: str
    bbox: tuple[float, float, float, float] | None
    label: str | None = None
    caption: str | None = None
    nearby_text: str | None = None


@dataclass(frozen=True)
class ParseResult:
    pages: list[ParsedPage]
    units: list[ParsedChunkUnit]
    assets: list[ParsedAsset] = field(default_factory=list)


class Parser(Protocol):
    name: str
    version: str

    def parse(self, path: Path, config: dict) -> ParseResult: ...
