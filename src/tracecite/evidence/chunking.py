"""Greedy char-budget chunker, normalisation, and chunk-identity hashing.

Parsers emit fine-grained ``ParsedChunkUnit`` sequences (for example, a PDF
text block, Markdown paragraph, or workbook row range). This module groups
adjacent units into retrieval-sized chunks and computes two identity
hashes:

- ``lexical_hash``: sha256 of the raw (unnormalised) chunk body.
- ``semantic_input_hash``: sha256 of
  ``normalisation_version + source_type + semantic_context + normalised body``.
  Path, line, page, and modification time are locators, not meaning, and are
  deliberately excluded.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field

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
    payload = (
        f"{normalisation_version}\x1f{source_type}\x1f{context}\x1f{normalised_body}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def group_units(
    units: list[ParsedChunkUnit], max_chars: int = DEFAULT_MAX_CHUNK_CHARS
) -> list[list[ParsedChunkUnit]]:
    """Greedily group consecutive units into chunks bounded by ``max_chars``.

    A single unit is never split, and a chunk never crosses a page. A new
    heading path starts a new chunk once the current chunk holds body text,
    so consecutive headings, such as a title and a subtitle or the short
    lines a PDF parser takes for headings, join the section that follows,
    even when its first unit alone exceeds ``max_chars``. A chunk shorter than
    a sixth of ``max_chars`` then takes in the sections that follow it on the
    same page while it stays within ``max_chars``, and a chunk of only digits,
    such as a lone page number, is dropped.
    """

    groups: list[list[ParsedChunkUnit]] = []
    lengths: list[int] = []
    current: list[ParsedChunkUnit] = []
    current_len = 0
    for unit in units:
        unit_len = len(unit.text)
        if current and (
            unit.physical_page != current[-1].physical_page
            or (
                (
                    current_len + unit_len > max_chars
                    or unit.heading_path != current[-1].heading_path
                )
                and any(part.content_type != "heading" for part in current)
            )
        ):
            _add_group(groups, lengths, current, current_len, max_chars)
            current = []
            current_len = 0
        current.append(unit)
        current_len += unit_len + 2
    if current:
        _add_group(groups, lengths, current, current_len, max_chars)
    return groups


def _add_group(
    groups: list[list[ParsedChunkUnit]],
    lengths: list[int],
    group: list[ParsedChunkUnit],
    group_len: int,
    max_chars: int,
) -> None:
    """Append a finished group, add it to a short previous group, or drop it
    when it holds only digits."""
    short = max_chars // 6
    if group_len < short and all(unit.text.strip().isdigit() for unit in group):
        return
    if (
        groups
        and lengths[-1] < short
        and group[0].content_type == "heading"
        and group[0].physical_page == groups[-1][-1].physical_page
        and lengths[-1] + group_len <= max_chars
    ):
        groups[-1].extend(group)
        lengths[-1] += group_len
    else:
        groups.append(group)
        lengths.append(group_len)


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

        physical_pages = {
            unit.physical_page for unit in group if unit.physical_page is not None
        }
        physical_page = first.physical_page if len(physical_pages) <= 1 else None
        page_range_start = min(physical_pages) if physical_pages else None
        page_range_end = max(physical_pages) if physical_pages else None
        heading_path = last.heading_path
        if first.heading_path != heading_path:
            # Leading headings join their section, and a chunk that spans
            # sibling sections belongs to the heading those sections share.
            heading_path = list(
                os.path.commonprefix(
                    [u.heading_path for u in group if u.content_type != "heading"]
                    or [heading_path]
                )
            )

        semantic_hash = compute_semantic_input_hash(
            normalisation_version=normalisation_version,
            source_type=source_type,
            heading_path=heading_path,
            symbol=first.symbol,
            body=body,
        )
        candidates.append(
            ChunkCandidate(
                logical_key=first.logical_key,
                ordinal=ordinal,
                heading_path=heading_path,
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
