"""Data contracts for deterministic table normalisation."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any, Literal

Severity = Literal["info", "warning", "error"]
SourceFormat = Literal["pandoc-markdown", "html"]
NORMALISER_VERSION = "pandoc-table-v1"


@dataclass(frozen=True, slots=True)
class TableContext:
    """Document context supplied by the caller or document extractor."""

    document_path: str = "<memory>"
    section_path: tuple[str, ...] = ()
    source_code_path: str | None = None
    table_id: str | None = None
    caption: str | None = None
    ordering: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def merged(self, **updates: Any) -> TableContext:
        values = {
            "document_path": self.document_path,
            "section_path": self.section_path,
            "source_code_path": self.source_code_path,
            "table_id": self.table_id,
            "caption": self.caption,
            "ordering": self.ordering,
            "metadata": dict(self.metadata),
        }
        values.update(
            {key: value for key, value in updates.items() if value is not None}
        )
        return TableContext(**values)


@dataclass(frozen=True, slots=True)
class TableDiagnostic:
    code: str
    severity: Severity
    message: str
    row: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class NormalisedTable:
    """Raw evidence, canonical table structure, and retrieval text."""

    table_id: str
    caption: str | None
    section_path: tuple[str, ...]
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    raw_source: str
    source_format: SourceFormat
    canonical_markdown: str
    normalised_text: str
    row_ids: tuple[str, ...]
    row_records: tuple[str, ...]
    diagnostics: tuple[TableDiagnostic, ...]
    document_path: str
    source_code_path: str | None
    source_hash: str
    normaliser_version: str = NORMALISER_VERSION
    supported: bool = True
    source_start_line: int | None = None
    source_end_line: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(item.severity == "error" for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["section_path"] = list(self.section_path)
        payload["headers"] = list(self.headers)
        payload["rows"] = [list(row) for row in self.rows]
        payload["row_ids"] = list(self.row_ids)
        payload["row_records"] = list(self.row_records)
        payload["diagnostics"] = [asdict(item) for item in self.diagnostics]
        payload["metadata"] = dict(self.metadata)
        return payload

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True
        )


class TableNormalisationError(ValueError):
    """Raised when strict normalisation cannot produce a trustworthy table."""


def source_hash(raw_source: str, context: TableContext) -> str:
    payload = {
        "raw_source": raw_source,
        "document_path": context.document_path,
        "section_path": list(context.section_path),
        "source_code_path": context.source_code_path,
        "table_id": context.table_id,
        "caption": context.caption,
        "ordering": context.ordering,
        "metadata": dict(context.metadata),
        "normaliser_version": NORMALISER_VERSION,
    }
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def expand_spans(
    rows: Iterable[Iterable[tuple[int, int, str] | None]],
    width: int,
    diagnostics: list[TableDiagnostic],
    row_label: str,
) -> list[list[str]]:
    """Expand row and column spans by repeating each spanning cell's text.

    Each cell is ``(rowspan, colspan, text)``, or None when its source shape
    is unsupported. ``row_label`` names the rows in diagnostics, such as
    ``HTML`` or ``body``.
    """
    pending: dict[int, tuple[int, str]] = {}
    expanded: list[list[str]] = []
    for row_number, cells in enumerate(rows, start=1):
        values: list[str | None] = [None] * width
        for column, (remaining, text) in list(pending.items()):
            if column < width:
                values[column] = text
            if remaining <= 1:
                del pending[column]
            else:
                pending[column] = (remaining - 1, text)

        cursor = 0
        for cell in cells:
            while cursor < width and values[cursor] is not None:
                cursor += 1
            if cursor >= width:
                diagnostics.append(
                    TableDiagnostic(
                        "table.extra-cell",
                        "error",
                        f"The {row_label} row contains more logical cells than the table width.",
                        row=row_number,
                    )
                )
                break
            if cell is None:
                diagnostics.append(
                    TableDiagnostic(
                        "table.unsupported-cell",
                        "error",
                        "A Pandoc table cell has an unsupported AST shape.",
                        row=row_number,
                        column=cursor + 1,
                    )
                )
                continue

            rowspan, colspan, text = cell
            if rowspan > 1 or colspan > 1:
                diagnostics.append(
                    TableDiagnostic(
                        "table.span-expanded",
                        "warning",
                        f"A {rowspan}x{colspan} cell span was expanded by repeating its visible value.",
                        row=row_number,
                        column=cursor + 1,
                    )
                )
            for offset in range(colspan):
                column = cursor + offset
                if column >= width:
                    diagnostics.append(
                        TableDiagnostic(
                            "table.span-overflow",
                            "error",
                            "A cell span exceeds the table width.",
                            row=row_number,
                            column=cursor + 1,
                        )
                    )
                    break
                values[column] = text
                if rowspan > 1:
                    pending[column] = (rowspan - 1, text)
            cursor += colspan

        expanded.append([value or "" for value in values])

    if pending:
        diagnostics.append(
            TableDiagnostic(
                "table.rowspan-overflow",
                "error",
                f"A row span extends beyond the final {row_label} row.",
            )
        )
    return expanded
