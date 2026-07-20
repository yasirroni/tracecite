"""Canonical table normalisation and deterministic retrieval text."""

from __future__ import annotations

from datetime import date, datetime
from functools import cmp_to_key
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from ._text import (
    cell_unit,
    collapse_space,
    escape_pipe_cell,
    header_unit,
    is_missing,
    normalise_label,
    slug,
)
from .models import (
    NormalisedTable,
    TableContext,
    TableDiagnostic,
    TableNormalisationError,
    source_hash,
)
from .pandoc import ParsedPandocTable, parse_pandoc_tables


_METADATA_RE = re.compile(
    r"<!--\s*(?:knowledge-table|tracecite-table)\s*:\s*(\{.*?\})\s*-->", re.S
)
_ORDINALS = {"index", "order", "position", "rank", "row"}
_DIRECTION_RE = re.compile(r"(.+?)\s+(ascending|descending)\b", re.I)
_NUMBER_RE = re.compile(r"^\s*[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ].*)?$")


def normalise_pandoc_table(
    source: str,
    *,
    context: TableContext | None = None,
    strict: bool = False,
    pandoc: str | Path | None = None,
    allow_pipe_fallback: bool = False,
) -> NormalisedTable:
    """Normalise exactly one Pandoc Markdown table.

    Pandoc is authoritative. The reduced fallback is limited to ordinary pipe
    tables and is used only when explicitly requested.
    """

    context = context or TableContext()
    metadata = _merged_metadata(source, context.metadata)
    parse_diagnostics: list[TableDiagnostic] = _pipe_source_diagnostics(source)

    try:
        parsed_tables = parse_pandoc_tables(source, pandoc=pandoc)
    except (FileNotFoundError, TableNormalisationError) as error:
        if not allow_pipe_fallback:
            raise
        parsed_tables = [_parse_pipe_fallback(source)]
        parse_diagnostics.append(
            TableDiagnostic(
                "table.pipe-fallback",
                "warning",
                f"Pandoc was unavailable or rejected the source; reduced pipe-table parsing was used: {error}",
            )
        )

    if len(parsed_tables) != 1:
        raise TableNormalisationError(
            f"normalise_pandoc_table expects exactly one table; found {len(parsed_tables)}"
        )

    parsed = parsed_tables[0]
    result = _build_normalised_table(
        parsed,
        raw_source=source,
        source_format="pandoc-markdown",
        context=context,
        metadata=metadata,
        extra_diagnostics=parse_diagnostics,
    )
    if strict and result.has_errors:
        raise TableNormalisationError(_strict_message(result))
    return result


def normalise_parsed_table(
    parsed: ParsedPandocTable,
    *,
    raw_source: str,
    context: TableContext,
    metadata: Mapping[str, Any] | None = None,
    source_format: str = "pandoc-markdown",
    extra_diagnostics: Iterable[TableDiagnostic] = (),
    strict: bool = False,
) -> NormalisedTable:
    """Build the public normal form from an already parsed Pandoc table."""

    result = _build_normalised_table(
        parsed,
        raw_source=raw_source,
        source_format=source_format,
        context=context,
        metadata=dict(metadata or {}),
        extra_diagnostics=list(extra_diagnostics),
    )
    if strict and result.has_errors:
        raise TableNormalisationError(_strict_message(result))
    return result


def _build_normalised_table(
    parsed: ParsedPandocTable,
    *,
    raw_source: str,
    source_format: str,
    context: TableContext,
    metadata: Mapping[str, Any],
    extra_diagnostics: Iterable[TableDiagnostic],
) -> NormalisedTable:
    labels = _string_map(metadata.get("labels"))
    units = _string_map(metadata.get("units"))
    row_identity = _string_list(metadata.get("row_identity"))
    description = _optional_text(metadata.get("description"))
    ordering = context.ordering or _optional_text(metadata.get("ordering"))

    raw_headers = [collapse_space(value) for value in parsed.headers]
    headers = [labels.get(header, header) for header in raw_headers]
    rows = [[collapse_space(value) for value in row] for row in parsed.rows]

    caption = context.caption or parsed.caption or description
    table_id = (
        context.table_id
        or parsed.table_id
        or _optional_text(metadata.get("table_id"))
        or _stable_table_id(
            caption, context.section_path, context.document_path, headers
        )
    )

    diagnostics = [*parsed.diagnostics, *extra_diagnostics]
    diagnostics.extend(
        _validate_table(
            headers=headers,
            raw_headers=raw_headers,
            rows=rows,
            units=units,
            ordering=ordering,
            row_identity=row_identity,
        )
    )

    canonical = _canonical_markdown(
        headers=headers,
        rows=rows,
        alignments=parsed.alignments,
        caption=caption,
        table_id=table_id,
    )
    normalised_text, row_ids, row_records = _render_retrieval_text(
        table_id=table_id,
        caption=caption,
        section_path=context.section_path,
        document_path=context.document_path,
        source_code_path=context.source_code_path,
        headers=headers,
        raw_headers=raw_headers,
        rows=rows,
        units=units,
        ordering=ordering,
        description=description,
        row_identity=row_identity,
    )

    supported = not any(
        item.severity == "error" and item.code.startswith("table.unsupported")
        for item in diagnostics
    )
    merged_metadata = {
        **dict(metadata),
        "labels": labels,
        "units": units,
        "row_identity": row_identity,
        "raw_headers": raw_headers,
    }
    if ordering:
        merged_metadata["ordering"] = ordering
    if description:
        merged_metadata["description"] = description

    return NormalisedTable(
        table_id=table_id,
        caption=caption,
        section_path=context.section_path,
        headers=tuple(headers),
        rows=tuple(tuple(row) for row in rows),
        raw_source=raw_source,
        source_format=source_format,  # type: ignore[arg-type]
        canonical_markdown=canonical,
        normalised_text=normalised_text,
        row_ids=tuple(row_ids),
        row_records=tuple(row_records),
        diagnostics=tuple(diagnostics),
        document_path=context.document_path,
        source_code_path=context.source_code_path,
        source_hash=source_hash(raw_source, context),
        supported=supported,
        source_start_line=_optional_int(metadata.get("source_start_line")),
        source_end_line=_optional_int(metadata.get("source_end_line")),
        metadata=merged_metadata,
    )


def _render_retrieval_text(
    *,
    table_id: str,
    caption: str | None,
    section_path: tuple[str, ...],
    document_path: str,
    source_code_path: str | None,
    headers: list[str],
    raw_headers: list[str],
    rows: list[list[str]],
    units: Mapping[str, str],
    ordering: str | None,
    description: str | None,
    row_identity: list[str],
) -> tuple[str, list[str], list[str]]:
    title = caption or description or (section_path[-1] if section_path else table_id)
    context_lines = [f"Table: {title}", f"Table identifier: {table_id}"]
    if document_path and document_path != "<memory>":
        context_lines.append(f"Source document: {document_path}")
    if source_code_path:
        context_lines.append(f"Executable source: {source_code_path}")
    if section_path:
        context_lines.append(f"Section: {' > '.join(section_path)}")
    if description and description != title:
        context_lines.append(f"Description: {description}")
    if ordering:
        context_lines.append(f"Ordering: {ordering}")
    if row_identity:
        context_lines.append(f"Row identity columns: {'; '.join(row_identity)}")
    context_lines.append(f"Columns: {'; '.join(headers)}")

    ordinal = _ordinal_index(headers)
    row_ids: list[str] = []
    row_records: list[str] = []
    row_paragraphs: list[str] = []
    for number, row in enumerate(rows, start=1):
        row_name = f"Row {number}"
        if ordinal is not None and ordinal < len(row) and not is_missing(row[ordinal]):
            row_name = f"{headers[ordinal]} {row[ordinal]}"

        fields: list[str] = []
        for index, (header, raw_header, value) in enumerate(
            zip(headers, raw_headers, row, strict=True)
        ):
            if index == ordinal:
                continue
            rendered = "not available" if is_missing(value) else value
            unit = units.get(raw_header) or units.get(header)
            if (
                unit
                and rendered != "not available"
                and not cell_unit(rendered)
                and unit not in header
            ):
                rendered = f"{rendered} {unit}"
            fields.append(f"{header}: {rendered}")

        sentence = _sentence(f"{row_name}. " + "; ".join(fields))
        row_id = _row_id(
            table_id=table_id,
            headers=headers,
            row=row,
            row_identity=row_identity,
        )
        row_paragraphs.append(sentence)
        row_ids.append(row_id)
        row_records.append(
            " ".join(_sentence(line) for line in context_lines) + " " + sentence
        )

    if not rows:
        row_paragraphs.append("This table contains no data rows.")

    return (
        "\n".join(context_lines) + "\n\n" + "\n\n".join(row_paragraphs),
        row_ids,
        row_records,
    )


def _validate_table(
    *,
    headers: list[str],
    raw_headers: list[str],
    rows: list[list[str]],
    units: Mapping[str, str],
    ordering: str | None,
    row_identity: list[str],
) -> list[TableDiagnostic]:
    diagnostics: list[TableDiagnostic] = []
    normalised_headers = [normalise_label(value) for value in headers]

    duplicates = sorted(
        {value for value in normalised_headers if normalised_headers.count(value) > 1}
    )
    if duplicates:
        diagnostics.append(
            TableDiagnostic(
                "table.duplicate-headers",
                "error",
                "Duplicate headers after normalisation: " + ", ".join(duplicates),
            )
        )

    if not rows:
        diagnostics.append(
            TableDiagnostic(
                "table.empty-body", "warning", "The table contains no data rows."
            )
        )

    seen_rows: set[tuple[str, ...]] = set()
    duplicate_rows = 0
    for row in rows:
        key = tuple(row)
        if key in seen_rows:
            duplicate_rows += 1
        seen_rows.add(key)
    if duplicate_rows:
        diagnostics.append(
            TableDiagnostic(
                "table.duplicate-rows",
                "warning",
                f"The table contains {duplicate_rows} duplicated data row(s).",
            )
        )

    ordinal = _ordinal_index(headers)
    if ordinal is not None:
        values = [row[ordinal].strip() for row in rows]
        present = [value for value in values if value]
        if len(present) != len(set(present)):
            diagnostics.append(
                TableDiagnostic(
                    "table.duplicate-rank",
                    "error",
                    f'Ordinal column "{headers[ordinal]}" contains duplicate values.',
                    column=ordinal + 1,
                )
            )
        numeric = [_number(value) for value in present]
        if present and all(value is not None for value in numeric):
            numbers = [float(value) for value in numeric if value is not None]
            if numbers != sorted(numbers):
                diagnostics.append(
                    TableDiagnostic(
                        "table.nonmonotonic-rank",
                        "warning",
                        f'Ordinal column "{headers[ordinal]}" is not monotonic ascending.',
                        column=ordinal + 1,
                    )
                )

    header_lookup = {
        normalise_label(header): index for index, header in enumerate(headers)
    }
    identity_indices: list[int] = []
    for identity in row_identity:
        index = header_lookup.get(normalise_label(identity))
        if index is None:
            diagnostics.append(
                TableDiagnostic(
                    "table.missing-row-identity-column",
                    "error",
                    f'Configured row identity column "{identity}" is not present.',
                )
            )
        else:
            identity_indices.append(index)

    if row_identity and len(identity_indices) == len(row_identity):
        seen_identity: dict[tuple[str, ...], int] = {}
        for row_number, row in enumerate(rows, start=1):
            key = tuple(row[index].strip() for index in identity_indices)
            missing_columns = [
                headers[index]
                for index, value in zip(identity_indices, key, strict=True)
                if is_missing(value)
            ]
            if missing_columns:
                diagnostics.append(
                    TableDiagnostic(
                        "table.missing-row-identity-value",
                        "error",
                        "Configured row identity contains a missing value in: "
                        + ", ".join(missing_columns),
                        row=row_number,
                    )
                )
                continue
            previous = seen_identity.get(key)
            if previous is not None:
                diagnostics.append(
                    TableDiagnostic(
                        "table.duplicate-row-identity",
                        "error",
                        f"Rows {previous} and {row_number} have the same configured row identity.",
                        row=row_number,
                    )
                )
            else:
                seen_identity[key] = row_number

    diagnostics.extend(_unit_diagnostics(headers, raw_headers, rows, units))
    if ordering:
        diagnostic = _ordering_diagnostic(headers, rows, ordering)
        if diagnostic:
            diagnostics.append(diagnostic)
    return diagnostics


def _unit_diagnostics(
    headers: list[str],
    raw_headers: list[str],
    rows: list[list[str]],
    units: Mapping[str, str],
) -> list[TableDiagnostic]:
    diagnostics: list[TableDiagnostic] = []
    for column, (header, raw_header) in enumerate(
        zip(headers, raw_headers, strict=True)
    ):
        declared = units.get(raw_header) or units.get(header) or header_unit(header)
        header_declared = header_unit(header)
        if (
            declared
            and header_declared
            and _unit_key(declared) != _unit_key(header_declared)
        ):
            diagnostics.append(
                TableDiagnostic(
                    "table.header-unit-conflict",
                    "warning",
                    f'Column "{header}" declares conflicting units "{header_declared}" and "{declared}".',
                    column=column + 1,
                )
            )

        observed: dict[str, tuple[str, list[int]]] = {}
        for row_number, row in enumerate(rows, start=1):
            unit = cell_unit(row[column]) if column < len(row) else None
            if unit:
                unit_key = _unit_key(unit)
                if unit_key not in observed:
                    observed[unit_key] = (unit, [])
                observed[unit_key][1].append(row_number)
                if declared and _unit_key(unit) != _unit_key(declared):
                    diagnostics.append(
                        TableDiagnostic(
                            "table.unit-conflict",
                            "warning",
                            f'Column "{header}" declares "{declared}" but row {row_number} contains "{unit}".',
                            row=row_number,
                            column=column + 1,
                        )
                    )
        if len(observed) > 1:
            labels = sorted(
                (label for label, _rows in observed.values()),
                key=str.casefold,
            )
            diagnostics.append(
                TableDiagnostic(
                    "table.mixed-units",
                    "warning",
                    f'Column "{header}" contains mixed explicit units: {", ".join(labels)}.',
                    column=column + 1,
                )
            )
    return diagnostics


def _ordering_diagnostic(
    headers: list[str],
    rows: list[list[str]],
    ordering: str,
) -> TableDiagnostic | None:
    clauses = []
    for match in _DIRECTION_RE.finditer(ordering.replace(" then ", ", ")):
        phrase = match.group(1).split(",")[-1].strip(" ,")
        direction = match.group(2).lower()
        index = _match_header(phrase, headers)
        if index is not None:
            clauses.append((index, direction))

    if not clauses:
        return TableDiagnostic(
            "table.ordering-unchecked",
            "info",
            f'Ordering metadata could not be matched conservatively to a column: "{ordering}".',
        )
    if len(rows) < 2:
        return None

    expected = sorted(
        range(len(rows)),
        key=cmp_to_key(lambda a, b: _compare_rows(rows[a], rows[b], clauses)),
    )
    if expected != list(range(len(rows))):
        return TableDiagnostic(
            "table.ordering-mismatch",
            "error",
            f'The row order is inconsistent with declared ordering "{ordering}".',
        )
    return None


def _compare_rows(
    left: list[str],
    right: list[str],
    clauses: list[tuple[int, str]],
) -> int:
    for index, direction in clauses:
        left_missing = is_missing(left[index])
        right_missing = is_missing(right[index])
        if left_missing != right_missing:
            return 1 if left_missing else -1
        left_value = _sort_value(left[index])
        right_value = _sort_value(right[index])
        if left_value == right_value:
            continue
        comparison = -1 if left_value < right_value else 1
        return -comparison if direction == "descending" else comparison
    return 0


def _sort_value(value: str) -> tuple[int, Any]:
    if is_missing(value):
        return (3, "")
    text = value.strip()
    if _ISO_DATE_RE.match(text):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return (1, parsed.timestamp())
        except ValueError:
            try:
                return (1, date.fromisoformat(text[:10]).toordinal())
            except ValueError:
                pass
    number = _number(value)
    if number is not None:
        return (0, number)
    return (2, text.casefold())


def _number(value: str) -> float | None:
    match = _NUMBER_RE.match(value)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _match_header(phrase: str, headers: list[str]) -> int | None:
    target = normalise_label(phrase)
    target_tokens = {
        item
        for item in target.split()
        if item not in {"by", "ordered", "sort", "sorted"}
    }
    best: tuple[int, int] | None = None
    for index, header in enumerate(headers):
        candidate = normalise_label(header)
        candidate_tokens = set(candidate.split())
        overlap = len(target_tokens & candidate_tokens)
        if candidate == target or candidate in target or target in candidate:
            overlap += 10
        if overlap and (best is None or overlap > best[0]):
            best = (overlap, index)
    return None if best is None else best[1]


def _canonical_markdown(
    *,
    headers: list[str],
    rows: list[list[str]],
    alignments: list[str],
    caption: str | None,
    table_id: str,
) -> str:
    header_line = "| " + " | ".join(escape_pipe_cell(value) for value in headers) + " |"
    separators = []
    for index in range(len(headers)):
        alignment = alignments[index] if index < len(alignments) else "default"
        separators.append(
            {"left": ":---", "center": ":---:", "right": "---:"}.get(alignment, "---")
        )
    lines = [header_line, "| " + " | ".join(separators) + " |"]
    lines.extend(
        "| " + " | ".join(escape_pipe_cell(value) for value in row) + " |"
        for row in rows
    )
    if caption:
        lines.extend(["", f": {caption} {{#{table_id}}}"])
    return "\n".join(lines)


def _stable_table_id(
    caption: str | None,
    section_path: tuple[str, ...],
    document_path: str,
    headers: list[str],
) -> str:
    title = caption or (section_path[-1] if section_path else "table")
    digest = sha256(
        json.dumps(
            {"document": document_path, "section": section_path, "headers": headers},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:8]
    return f"{slug(title)}-{digest}"


def _merged_metadata(source: str, supplied: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    match = _METADATA_RE.search(source)
    if match:
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError as error:
            raise TableNormalisationError(
                f"Invalid table metadata JSON: {error}"
            ) from error
        if not isinstance(value, dict):
            raise TableNormalisationError("Table metadata must be a JSON object")
        payload.update(value)
    payload.update(dict(supplied))
    return payload


def _sentence(value: str) -> str:
    text = collapse_space(value).rstrip()
    if not text:
        return ""
    return text if text.endswith((".", "!", "?")) else text + "."


def _row_id(
    *,
    table_id: str,
    headers: list[str],
    row: list[str],
    row_identity: list[str],
) -> str:
    lookup = {normalise_label(header): index for index, header in enumerate(headers)}
    identity_indices = [lookup.get(normalise_label(label)) for label in row_identity]
    if row_identity and all(index is not None for index in identity_indices):
        identity = [
            [headers[int(index)], row[int(index)]]
            for index in identity_indices
            if index is not None
        ]
        payload: dict[str, Any] = {"identity": identity}
    else:
        payload = {"row": list(zip(headers, row, strict=True))}
    digest = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"{table_id}:row-{digest}"


def _pipe_source_diagnostics(source: str) -> list[TableDiagnostic]:
    """Diagnose ragged ordinary pipe rows before Pandoc fills missing cells."""

    lines = source.splitlines()
    fence: tuple[str, int] | None = None
    for index in range(len(lines) - 1):
        token = re.match(r"^\s*(`{3,}|~{3,})", lines[index])
        if token:
            marker = token.group(1)[0]
            length = len(token.group(1))
            if fence is None:
                fence = (marker, length)
            elif marker == fence[0] and length >= fence[1]:
                fence = None
            continue
        if fence is not None:
            continue
        if "|" not in lines[index] or "|" not in lines[index + 1]:
            continue
        headers = _split_pipe_row(lines[index])
        separators = _split_pipe_row(lines[index + 1])
        if not headers or len(headers) != len(separators):
            continue
        if not all(re.fullmatch(r":?-{3,}:?", item.strip()) for item in separators):
            continue

        diagnostics: list[TableDiagnostic] = []
        expected = len(headers)
        cursor = index + 2
        row_number = 0
        while cursor < len(lines):
            line = lines[cursor]
            stripped = line.strip()
            if not stripped or stripped.startswith(":") or "|" not in line:
                break
            row_number += 1
            width = len(_split_pipe_row(line))
            if width != expected:
                diagnostics.append(
                    TableDiagnostic(
                        "table.ragged-row",
                        "error",
                        f"Pipe row has {width} cell(s); the header declares {expected}.",
                        row=row_number,
                    )
                )
            cursor += 1
        return diagnostics
    return []


def _parse_pipe_fallback(source: str) -> ParsedPandocTable:
    lines = source.splitlines()
    candidates = []
    for index in range(len(lines) - 1):
        if "|" not in lines[index] or "|" not in lines[index + 1]:
            continue
        headers = _split_pipe_row(lines[index])
        separators = _split_pipe_row(lines[index + 1])
        if len(headers) == len(separators) and all(
            re.fullmatch(r":?-{3,}:?", item.strip()) for item in separators
        ):
            candidates.append(index)
    if len(candidates) != 1:
        raise TableNormalisationError(
            f"Reduced fallback expects one ordinary pipe table; found {len(candidates)}"
        )
    index = candidates[0]
    headers = _split_pipe_row(lines[index])
    alignments = []
    for item in _split_pipe_row(lines[index + 1]):
        item = item.strip()
        if item.startswith(":") and item.endswith(":"):
            alignments.append("center")
        elif item.startswith(":"):
            alignments.append("left")
        elif item.endswith(":"):
            alignments.append("right")
        else:
            alignments.append("default")
    rows = []
    cursor = index + 2
    while cursor < len(lines) and "|" in lines[cursor]:
        row = _split_pipe_row(lines[cursor])
        if len(row) != len(headers):
            break
        rows.append(row)
        cursor += 1
    caption = None
    table_id = None
    while cursor < len(lines) and not lines[cursor].strip():
        cursor += 1
    if cursor < len(lines) and lines[cursor].lstrip().startswith(":"):
        caption = lines[cursor].lstrip()[1:].strip()
        match = re.search(r"\s*\{#([A-Za-z][A-Za-z0-9_.:-]*)\}\s*$", caption)
        if match:
            table_id = match.group(1)
            caption = caption[: match.start()].strip()
    return ParsedPandocTable(
        table_id=table_id,
        caption=caption,
        headers=headers,
        rows=rows,
        alignments=alignments,
        diagnostics=[],
        attributes={},
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
            cells.append(collapse_space("".join(current)))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    cells.append(collapse_space("".join(current)))
    return cells


def _ordinal_index(headers: list[str]) -> int | None:
    for index, header in enumerate(headers):
        if normalise_label(header) in _ORDINALS:
            return index
    return None


def _string_map(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TableNormalisationError("labels and units metadata must be mappings")
    return {str(key): str(item) for key, item in value.items()}


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise TableNormalisationError("row_identity metadata must be an array")
    return [str(item) for item in value]


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = collapse_space(str(value))
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unit_key(value: str) -> str:
    return collapse_space(value).replace(" ", "").casefold()


def _strict_message(table: NormalisedTable) -> str:
    errors = [item.message for item in table.diagnostics if item.severity == "error"]
    return f"Table {table.table_id} failed strict normalisation: " + "; ".join(errors)
