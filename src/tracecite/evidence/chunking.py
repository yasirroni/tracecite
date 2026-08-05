"""Greedy char-budget chunker, normalisation, and chunk-identity hashing.

Parsers emit fine-grained ``ParsedChunkUnit`` sequences (for example, a PDF
text block, Markdown paragraph, or workbook row range). This module groups
adjacent units into retrieval-sized chunks and computes the two identity
hashes plan 0006 requires:

- ``lexical_hash``: sha256 of the raw (unnormalised) chunk body.
- ``semantic_input_hash``: sha256 of
  ``normalisation_version + source_type + semantic_context + normalised body``.
  Path, line, page, and modification time are locators, not meaning, and are
  deliberately excluded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re

from .parsers.base import ParsedChunkUnit

DEFAULT_MAX_CHUNK_CHARS = 1200
_CELL_REFERENCE_RE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


@dataclass(frozen=True)
class ChunkCandidate:
    logical_key: str
    ordinal: int
    heading_path: list[str]
    symbol: str | None
    body: str
    content_type: str
    physical_page: int | None
    page_start_offset: int | None
    page_end_offset: int | None
    page_range_start: int | None
    page_range_end: int | None
    line_start: int | None
    line_end: int | None
    locator: dict = field(default_factory=dict)
    semantic_input_hash: str = ""
    lexical_hash: str = ""


def normalise_text(text: str) -> str:
    """Collapse whitespace so trivial reflow never changes semantic identity."""

    return " ".join(text.split())


def compute_lexical_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def compute_semantic_input_hash(
    *,
    normalisation_version: str,
    source_type: str,
    heading_path: list[str],
    symbol: str | None,
    body: str,
) -> str:
    normalised_body = normalise_text(body)
    context = json.dumps([heading_path, symbol], sort_keys=True)
    payload = "\x1f".join([normalisation_version, source_type, context, normalised_body])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def group_units(
    units: list[ParsedChunkUnit], max_chars: int = DEFAULT_MAX_CHUNK_CHARS
) -> list[list[ParsedChunkUnit]]:
    """Greedily group consecutive units into chunks bounded by ``max_chars``.

    A single unit is never split. Grouping only combines adjacent units that
    share the same heading path so a chunk never silently straddles a
    section boundary.
    """

    groups: list[list[ParsedChunkUnit]] = []
    current: list[ParsedChunkUnit] = []
    current_len = 0
    for unit in units:
        unit_len = len(unit.text)
        breaks_group = (
            current
            and (
                current_len + unit_len > max_chars
                or unit.heading_path != current[-1].heading_path
                or unit.physical_page != current[-1].physical_page
            )
        )
        if breaks_group:
            groups.append(current)
            current = []
            current_len = 0
        current.append(unit)
        current_len += unit_len + 2
    if current:
        groups.append(current)
    return groups


def _cell_coordinates(reference: str) -> tuple[int, int] | None:
    match = _CELL_REFERENCE_RE.fullmatch(reference)
    if match is None:
        return None
    column = 0
    for character in match.group(1):
        column = column * 26 + ord(character) - ord("A") + 1
    return column, int(match.group(2))


def _column_label(column: int) -> str:
    label = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        label = chr(ord("A") + remainder) + label
    return label


def _excel_bounding_range(locators: list[dict]) -> str | None:
    coordinates: list[tuple[int, int]] = []
    for locator in locators:
        for key in ("start_cell", "end_cell"):
            parsed = _cell_coordinates(str(locator.get(key, "")))
            if parsed is None:
                return None
            coordinates.append(parsed)
    min_column = min(column for column, _row in coordinates)
    max_column = max(column for column, _row in coordinates)
    min_row = min(row for _column, row in coordinates)
    max_row = max(row for _column, row in coordinates)
    start = f"{_column_label(min_column)}{min_row}"
    end = f"{_column_label(max_column)}{max_row}"
    return start if start == end else f"{start}:{end}"


def _merged_locator(group: list[ParsedChunkUnit]) -> dict:
    locators = [unit.locator for unit in group if unit.locator]
    if not locators:
        return {"unit_count": len(group)}
    if all(locator.get("kind") == "excel-range" for locator in locators):
        sheets = {locator.get("sheet") for locator in locators}
        if len(sheets) == 1:
            first = locators[0]
            exact_ranges = [locator["range"] for locator in locators]
            return {
                "kind": "excel-range",
                "sheet": first.get("sheet"),
                "sheet_index": first.get("sheet_index"),
                "sheet_state": first.get("sheet_state"),
                "range": _excel_bounding_range(locators),
                "range_kind": "bounding",
                "exact_ranges": exact_ranges,
                "row_start": min(locator["row_start"] for locator in locators),
                "row_end": max(locator["row_end"] for locator in locators),
                "unit_count": len(group),
            }
    if len(locators) == 1:
        return {**locators[0], "unit_count": len(group)}
    return {"unit_count": len(group), "parts": locators}


def build_chunk_candidates(
    groups: list[list[ParsedChunkUnit]],
    *,
    source_type: str,
    normalisation_version: str,
) -> list[ChunkCandidate]:
    candidates: list[ChunkCandidate] = []
    for ordinal, group in enumerate(groups):
        first = group[0]
        last = group[-1]
        body = "\n\n".join(unit.text for unit in group)
        content_types = {unit.content_type for unit in group}
        content_type = first.content_type if len(content_types) == 1 else "mixed"

        physical_pages = {unit.physical_page for unit in group if unit.physical_page is not None}
        physical_page = first.physical_page if len(physical_pages) <= 1 else None
        page_range_start = min(physical_pages) if physical_pages else None
        page_range_end = max(physical_pages) if physical_pages else None

        semantic_hash = compute_semantic_input_hash(
            normalisation_version=normalisation_version,
            source_type=source_type,
            heading_path=first.heading_path,
            symbol=first.symbol,
            body=body,
        )
        candidates.append(
            ChunkCandidate(
                logical_key=first.logical_key,
                ordinal=ordinal,
                heading_path=first.heading_path,
                symbol=first.symbol,
                body=body,
                content_type=content_type,
                physical_page=physical_page,
                page_start_offset=first.page_start_offset,
                page_end_offset=last.page_end_offset,
                page_range_start=page_range_start,
                page_range_end=page_range_end,
                line_start=first.line_start,
                line_end=last.line_end,
                locator=_merged_locator(group),
                semantic_input_hash=semantic_hash,
                lexical_hash=compute_lexical_hash(body),
            )
        )
    return candidates
