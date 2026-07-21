"""Greedy char-budget chunker, normalisation, and chunk-identity hashing.

Parsers emit fine-grained ``ParsedChunkUnit`` sequences (one per PDF text
block or Markdown paragraph). This module groups adjacent units into
retrieval-sized chunks and computes the two identity hashes plan 0006
requires:

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

from .parsers.base import ParsedChunkUnit

DEFAULT_MAX_CHUNK_CHARS = 1200


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
                locator={"unit_count": len(group)},
                semantic_input_hash=semantic_hash,
                lexical_hash=compute_lexical_hash(body),
            )
        )
    return candidates
