"""Whole-document table extraction and embedding-Markdown augmentation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from bs4 import BeautifulSoup

from .models import (
    NormalisedTable,
    TableContext,
    TableDiagnostic,
    TableNormalisationError,
    source_hash,
)
from .normalise import normalise_pandoc_table, normalise_parsed_table
from .html import normalise_html_table
from .pandoc import ParsedPandocTable, ast_tables_with_sections
from .render import render_embedding_block, strip_embedding_blocks


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_RAW_HTML_FENCE_RE = re.compile(
    r"^\s*(`{3,}|~{3,})\s*(?:@raw\s+html|\{=html\})\s*$",
    re.I,
)
_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")
_METADATA_RE = re.compile(
    r"^\s*<!--\s*(?:knowledge-table|tracecite-table)\s*:\s*(\{.*\})\s*-->\s*$"
)
_CAPTION_RE = re.compile(r"^\s*:\s+.+")
_TABLE_OPEN_RE = re.compile(r"<table\b", re.I)
_TABLE_CLOSE_RE = re.compile(r"</table\s*>", re.I)
_TABLE_TOKEN_RE = re.compile(r"</?table\b[^>]*>", re.I | re.S)
_TABLE_ID_RE = re.compile(r"\{#([A-Za-z][A-Za-z0-9_.:-]*)\}")
_HTML_TABLE_ID_RE = re.compile(
    r"<table\b[^>]*\bid\s*=\s*(['\"])([A-Za-z][A-Za-z0-9_.:-]*)\1",
    re.I | re.S,
)


@dataclass(frozen=True, slots=True)
class DocumentTransform:
    markdown: str
    tables: tuple[NormalisedTable, ...]


def normalise_document_tables(
    markdown: str,
    *,
    document_path: str = "<memory>",
    source_code_path: str | None = None,
    strict: bool = False,
    pandoc: str | Path | None = None,
    allow_pipe_fallback: bool = False,
) -> list[NormalisedTable]:
    """Extract native Markdown and raw-HTML tables from one generated document."""

    scanned = _scan_tables(markdown)
    tables: list[NormalisedTable] = []

    for candidate in scanned:
        context = TableContext(
            document_path=document_path,
            section_path=candidate.section_path,
            source_code_path=source_code_path,
            metadata={
                **candidate.metadata,
                "source_start_line": candidate.start + 1,
                "source_end_line": candidate.end,
            },
        )
        try:
            if candidate.kind == "html":
                table = normalise_html_table(
                    candidate.source,
                    context=context,
                    strict=False,
                    pandoc=pandoc,
                )
            else:
                table = normalise_pandoc_table(
                    candidate.source,
                    context=context,
                    strict=False,
                    pandoc=pandoc,
                    allow_pipe_fallback=allow_pipe_fallback,
                )
        except TableNormalisationError as error:
            if strict:
                raise
            table = _failed_candidate_table(candidate, context, error)
        if candidate.diagnostics:
            diagnostics = (*table.diagnostics, *candidate.diagnostics)
            table = replace(
                table,
                diagnostics=diagnostics,
                supported=table.supported
                and not any(
                    item.severity == "error"
                    and item.code.startswith("table.unsupported")
                    for item in candidate.diagnostics
                ),
            )
        if strict and table.has_errors:
            raise TableNormalisationError(
                f"Table {table.table_id} failed strict normalisation: "
                + "; ".join(
                    item.message
                    for item in table.diagnostics
                    if item.severity == "error"
                )
            )
        tables.append(table)

    # Pandoc discovers grid, multiline, and simple tables that the exact-source
    # scanner deliberately does not guess at. Their raw source is canonicalised
    # and explicitly diagnosed rather than silently misidentified.
    try:
        ast_tables = ast_tables_with_sections(markdown, pandoc=pandoc)
    except (FileNotFoundError, TableNormalisationError):
        ast_tables = []

    unmatched = list(tables)
    for section_path, parsed in ast_tables:
        match_index = _find_matching_table(parsed, unmatched)
        if match_index is not None:
            unmatched.pop(match_index)
            continue

        context = TableContext(
            document_path=document_path,
            section_path=section_path,
            source_code_path=source_code_path,
        )
        table = normalise_parsed_table(
            parsed,
            raw_source="",
            context=context,
            extra_diagnostics=(
                TableDiagnostic(
                    "table.raw-source-canonicalised",
                    "warning",
                    "Exact source boundaries were unavailable; raw evidence uses Pandoc's canonical table representation.",
                ),
            ),
            strict=False,
        )
        table = replace(
            table,
            raw_source=table.canonical_markdown,
            source_hash=source_hash(table.canonical_markdown, context),
        )
        tables.append(table)

    tables.sort(
        key=lambda item: (
            item.source_start_line is None,
            item.source_start_line or 10**9,
        )
    )
    tables = _diagnose_duplicate_ids(tables)
    if strict:
        errors = [table for table in tables if table.has_errors]
        if errors:
            raise TableNormalisationError(
                f"{document_path} contains {len(errors)} table(s) with strict errors"
            )
    return tables


def augment_document_with_embedding_text(
    markdown: str,
    *,
    document_path: str = "<memory>",
    source_code_path: str | None = None,
    strict: bool = False,
    pandoc: str | Path | None = None,
    allow_pipe_fallback: bool = False,
) -> DocumentTransform:
    """Keep raw tables and append visible normalised records in a copy."""

    clean = strip_embedding_blocks(markdown)
    tables = normalise_document_tables(
        clean,
        document_path=document_path,
        source_code_path=source_code_path,
        strict=strict,
        pandoc=pandoc,
        allow_pipe_fallback=allow_pipe_fallback,
    )
    lines = clean.splitlines()
    inserts: dict[int, list[str]] = {}
    appendices: list[str] = []
    for table in tables:
        block = render_embedding_block(table)
        if table.source_end_line is None:
            appendices.append(block)
        else:
            inserts.setdefault(table.source_end_line, []).append(block)

    for index in sorted(inserts, reverse=True):
        payload: list[str] = [""]
        for block in inserts[index]:
            payload.extend([block, ""])
        lines[index:index] = payload

    if appendices:
        lines.extend(["", "## TraceCite table appendix", ""])
        for block in appendices:
            lines.extend([block, ""])

    result = "\n".join(lines).rstrip() + "\n"
    return DocumentTransform(result, tuple(tables))


@dataclass(slots=True)
class _Candidate:
    kind: str
    start: int
    end: int
    source: str
    section_path: tuple[str, ...]
    metadata: dict[str, Any]
    diagnostics: tuple[TableDiagnostic, ...] = ()


def _scan_tables(markdown: str) -> list[_Candidate]:
    lines = markdown.splitlines()
    candidates: list[_Candidate] = []
    headings: list[str] = []
    fence: tuple[str, int] | None = None
    pending_metadata: tuple[int, dict[str, Any]] | None = None
    index = 0

    while index < len(lines):
        line = lines[index]

        if fence is None:
            raw_fence = _RAW_HTML_FENCE_RE.match(line)
            if raw_fence:
                closing = _find_fence_end(lines, index, raw_fence.group(1))
                if closing is None:
                    pending_metadata = None
                    index += 1
                    continue
                block_source = "\n".join(lines[index + 1 : closing])
                fragments = _extract_html_table_fragments(block_source)
                start = pending_metadata[0] if pending_metadata else index
                for fragment_index, fragment in enumerate(fragments):
                    candidates.append(
                        _Candidate(
                            "html",
                            start,
                            closing + 1,
                            fragment,
                            tuple(item for item in headings if item),
                            pending_metadata[1]
                            if pending_metadata and fragment_index == 0
                            else {},
                        )
                    )
                pending_metadata = None
                index = closing + 1
                continue

        fence = _update_fence(line, fence)
        if fence is not None:
            index += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            headings = headings[: max(0, level - 1)]
            while len(headings) < level - 1:
                headings.append("")
            headings.append(heading.group(2).strip())
            pending_metadata = None
            index += 1
            continue

        metadata_match = _METADATA_RE.match(line)
        if metadata_match:
            try:
                payload = json.loads(metadata_match.group(1))
            except json.JSONDecodeError:
                payload = {}
            pending_metadata = (index, payload if isinstance(payload, dict) else {})
            index += 1
            continue

        if not line.strip():
            index += 1
            continue

        if _TABLE_OPEN_RE.search(line):
            start = pending_metadata[0] if pending_metadata else index
            depth = 0
            cursor = index
            while cursor < len(lines):
                depth += len(_TABLE_OPEN_RE.findall(lines[cursor]))
                depth -= len(_TABLE_CLOSE_RE.findall(lines[cursor]))
                cursor += 1
                if depth <= 0:
                    break
            if depth > 0:
                pending_metadata = None
                index += 1
                continue
            html_source = "\n".join(lines[index:cursor])
            fragments = _extract_html_table_fragments(html_source)
            for fragment_index, fragment in enumerate(fragments):
                candidates.append(
                    _Candidate(
                        "html",
                        start,
                        cursor,
                        fragment,
                        tuple(item for item in headings if item),
                        pending_metadata[1]
                        if pending_metadata and fragment_index == 0
                        else {},
                    )
                )
            pending_metadata = None
            index = cursor
            continue

        if _looks_like_pipe_table(lines, index):
            start = pending_metadata[0] if pending_metadata else index
            cursor = index + 2
            while cursor < len(lines):
                stripped = lines[cursor].strip()
                if not stripped or stripped.startswith(":") or "|" not in lines[cursor]:
                    break
                cursor += 1
            caption_index = cursor
            while caption_index < len(lines) and not lines[caption_index].strip():
                caption_index += 1
            if caption_index < len(lines) and _CAPTION_RE.match(lines[caption_index]):
                cursor = caption_index + 1
            source = "\n".join(lines[start:cursor])
            candidates.append(
                _Candidate(
                    "pandoc",
                    start,
                    cursor,
                    source,
                    tuple(item for item in headings if item),
                    pending_metadata[1] if pending_metadata else {},
                )
            )
            pending_metadata = None
            index = cursor
            continue

        pending_metadata = None
        index += 1

    return candidates


def _looks_like_pipe_table(lines: list[str], index: int) -> bool:
    if (
        index + 1 >= len(lines)
        or "|" not in lines[index]
        or "|" not in lines[index + 1]
    ):
        return False
    headers = _split_pipe_row(lines[index])
    separator = _split_pipe_row(lines[index + 1])
    return (
        len(headers) == len(separator)
        and bool(headers)
        and all(_SEPARATOR_RE.fullmatch(value.strip()) for value in separator)
    )


def _split_pipe_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in stripped:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())
    return cells


def _update_fence(line: str, fence: tuple[str, int] | None) -> tuple[str, int] | None:
    match = _FENCE_RE.match(line)
    if not match:
        return fence
    token = match.group(1)
    marker, length = token[0], len(token)
    if fence is None:
        return marker, length
    if marker == fence[0] and length >= fence[1]:
        return None
    return fence


def _find_matching_table(
    parsed: ParsedPandocTable,
    candidates: list[NormalisedTable],
) -> int | None:
    target_headers = tuple(value.strip() for value in parsed.headers)
    target_rows = tuple(tuple(value.strip() for value in row) for row in parsed.rows)
    for index, table in enumerate(candidates):
        if (
            not table.supported
            and parsed.table_id
            and table.table_id == parsed.table_id
        ):
            return index
        raw_headers = tuple(
            str(value).strip() for value in table.metadata.get("raw_headers", ())
        )
        raw_rows = tuple(
            tuple(str(value).strip() for value in row)
            for row in table.metadata.get("raw_rows", ())
        )
        identifier_matches = not parsed.table_id or table.table_id == parsed.table_id
        headers_match = table.headers == target_headers or raw_headers == target_headers
        rows_match = table.rows == target_rows or raw_rows == target_rows
        if identifier_matches and headers_match and rows_match:
            return index
    return None


def _failed_candidate_table(
    candidate: _Candidate,
    context: TableContext,
    error: TableNormalisationError,
) -> NormalisedTable:
    """Preserve a discovered table as raw evidence when safe parsing fails."""

    table_id = _candidate_table_id(candidate)
    caption = context.caption or _candidate_caption(candidate)
    if table_id is None:
        signature = {
            "document_path": context.document_path,
            "section_path": list(context.section_path),
            "caption": caption,
            "source_start_line": candidate.start + 1,
            "source_format": candidate.kind,
        }
        digest = sha256(
            json.dumps(signature, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:8]
        table_id = f"table-{digest}"

    diagnostic = TableDiagnostic(
        "table.normalisation-failed",
        "error",
        f"Table was preserved as raw evidence because normalisation failed: {error}",
    )
    raw_headers, raw_rows = _candidate_pipe_signature(candidate)
    metadata = {
        **dict(context.metadata),
        "normalisation_error": str(error),
        "raw_headers": raw_headers,
        "raw_rows": raw_rows,
    }
    failure_context = context.merged(table_id=table_id, caption=caption)
    return NormalisedTable(
        table_id=table_id,
        caption=caption,
        section_path=context.section_path,
        headers=(),
        rows=(),
        raw_source=candidate.source,
        source_format=("html" if candidate.kind == "html" else "pandoc-markdown"),
        canonical_markdown="",
        normalised_text="",
        row_ids=(),
        row_records=(),
        diagnostics=(diagnostic, *candidate.diagnostics),
        document_path=context.document_path,
        source_code_path=context.source_code_path,
        source_hash=source_hash(candidate.source, failure_context),
        supported=False,
        source_start_line=candidate.start + 1,
        source_end_line=candidate.end,
        metadata=metadata,
    )


def _candidate_table_id(candidate: _Candidate) -> str | None:
    metadata_id = candidate.metadata.get("table_id") or candidate.metadata.get("id")
    if isinstance(metadata_id, str) and metadata_id.strip():
        return metadata_id.strip()
    if candidate.kind == "html":
        match = _HTML_TABLE_ID_RE.search(candidate.source)
        return match.group(2) if match else None
    matches = _TABLE_ID_RE.findall(candidate.source)
    return matches[-1] if matches else None


def _candidate_caption(candidate: _Candidate) -> str | None:
    if candidate.kind == "html":
        soup = BeautifulSoup(candidate.source, "html.parser")
        caption = soup.find("caption")
        return caption.get_text(" ", strip=True) if caption else None
    for line in reversed(candidate.source.splitlines()):
        if not _CAPTION_RE.match(line):
            continue
        caption = line.lstrip()[1:].strip()
        caption = _TABLE_ID_RE.sub("", caption).strip()
        return caption or None
    return None


def _candidate_pipe_signature(
    candidate: _Candidate,
) -> tuple[list[str], list[list[str]]]:
    if candidate.kind != "pandoc":
        return [], []
    lines = candidate.source.splitlines()
    for index in range(len(lines) - 1):
        if not _looks_like_pipe_table(lines, index):
            continue
        headers = _split_pipe_row(lines[index])
        rows: list[list[str]] = []
        cursor = index + 2
        while cursor < len(lines):
            stripped = lines[cursor].strip()
            if not stripped or stripped.startswith(":") or "|" not in lines[cursor]:
                break
            row = _split_pipe_row(lines[cursor])
            if len(row) != len(headers):
                break
            rows.append(row)
            cursor += 1
        return headers, rows
    return [], []


def _find_fence_end(lines: list[str], start: int, opening: str) -> int | None:
    marker = opening[0]
    minimum = len(opening)
    for index in range(start + 1, len(lines)):
        match = _FENCE_RE.match(lines[index])
        if not match:
            continue
        token = match.group(1)
        if (
            token[0] == marker
            and len(token) >= minimum
            and not lines[index][match.end() :].strip()
        ):
            return index
    return None


def _extract_html_table_fragments(source: str) -> list[str]:
    """Return byte-preserving top-level ``<table>`` fragments from HTML text."""

    fragments: list[str] = []
    depth = 0
    start: int | None = None
    for match in _TABLE_TOKEN_RE.finditer(source):
        closing = match.group(0).lstrip().lower().startswith("</")
        if not closing:
            if depth == 0:
                start = match.start()
            depth += 1
            continue
        if depth == 0:
            continue
        depth -= 1
        if depth == 0 and start is not None:
            fragments.append(source[start : match.end()])
            start = None

    if fragments:
        return fragments

    # Malformed but parseable HTML is still useful as evidence. BeautifulSoup's
    # fallback is explicit because it cannot preserve the source byte-for-byte.
    soup = BeautifulSoup(source, "html.parser")
    return [
        str(table)
        for table in soup.find_all("table")
        if table.find_parent("table") is None
    ]


def _diagnose_duplicate_ids(tables: list[NormalisedTable]) -> list[NormalisedTable]:
    counts: dict[str, int] = {}
    result: list[NormalisedTable] = []
    for table in tables:
        counts[table.table_id] = counts.get(table.table_id, 0) + 1
        if counts[table.table_id] == 1:
            result.append(table)
            continue
        diagnostic = TableDiagnostic(
            "table.duplicate-id",
            "error",
            f'Duplicate explicit or derived table identifier "{table.table_id}" in one document.',
        )
        result.append(replace(table, diagnostics=(*table.diagnostics, diagnostic)))
    return result
