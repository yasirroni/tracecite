"""Data contracts for deterministic table normalisation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from typing import Any, Literal, Mapping


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

    def merged(self, **updates: Any) -> "TableContext":
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
