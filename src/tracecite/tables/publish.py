"""Optional DataFrame helper for emitting safe Pandoc pipe tables."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from html import escape as html_escape
import json
import re
from typing import Any

import pandas as pd
from tabulate import tabulate


Formatter = str | Callable[[Any], str]
_TABLE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")


def knowledge_table(
    table: pd.DataFrame,
    *,
    table_id: str,
    caption: str | None = None,
    columns: Sequence[str] | None = None,
    labels: Mapping[str, str] | None = None,
    formats: Mapping[str, Formatter] | None = None,
    units: Mapping[str, str] | None = None,
    ordering: str | None = None,
    row_identity: Sequence[str] | None = None,
    description: str | None = None,
    summary: bool | Sequence[str] = False,
) -> str:
    """Return one Pandoc table with optional semantic metadata."""

    if not _TABLE_ID_RE.fullmatch(table_id):
        raise ValueError(
            "table_id must start with a letter and contain only letters, digits, "
            "underscore, dot, colon, or hyphen"
        )

    labels = dict(labels or {})
    formats = dict(formats or {})
    units = dict(units or {})
    selected = list(columns or table.columns)
    _require_columns(table, selected)
    _require_known_keys("labels", labels, selected)
    _require_known_keys("formats", formats, selected)
    _require_known_keys("units", units, selected)

    identity = list(row_identity or [])
    _require_columns(table, identity)
    display_headers = [labels.get(column, _humanise(column)) for column in selected]
    if len(set(display_headers)) != len(display_headers):
        raise ValueError("Displayed column labels must be unique")

    rows = [
        [
            _escape_cell(_format_value(value, formats.get(column)))
            for column, value in zip(selected, row, strict=True)
        ]
        for row in table.loc[:, selected].itertuples(index=False, name=None)
    ]
    alignments = tuple(
        "right" if pd.api.types.is_numeric_dtype(table[column]) else "left"
        for column in selected
    )

    metadata = table_metadata_comment(
        table_id=table_id if caption is None else None,
        description=description,
        ordering=ordering,
        units={
            labels.get(column, _humanise(column)): unit
            for column, unit in units.items()
        },
        row_identity=[labels.get(column, _humanise(column)) for column in identity],
    )
    parts: list[str] = []
    if metadata:
        parts.extend([metadata, ""])
    parts.extend(
        [
            tabulate(
                rows,
                headers=[_escape_cell(header) for header in display_headers],
                tablefmt="pipe",
                disable_numparse=True,
                colalign=alignments,
            ),
            "",
        ]
    )
    if caption is not None:
        parts.append(f": {caption} {{#{table_id}}}")

    if summary is not False:
        summary_columns = selected if summary is True else list(summary)
        _require_columns(table, summary_columns)
        parts.extend(
            [
                "",
                computed_first_row_summary(
                    table,
                    columns=summary_columns,
                    labels=labels,
                    units=units,
                    formats=formats,
                ),
            ]
        )
    return "\n".join(parts)


def table_metadata_comment(
    *,
    table_id: str | None = None,
    description: str | None = None,
    ordering: str | None = None,
    labels: Mapping[str, str] | None = None,
    units: Mapping[str, str] | None = None,
    row_identity: Sequence[str] | None = None,
) -> str:
    payload = {
        key: value
        for key, value in {
            "table_id": table_id,
            "description": description,
            "ordering": ordering,
            "labels": dict(labels or {}),
            "units": dict(units or {}),
            "row_identity": list(row_identity or []),
        }.items()
        if value
    }
    if not payload:
        return ""
    return f"<!-- tracecite-table: {json.dumps(payload, ensure_ascii=False, sort_keys=True)} -->"


def computed_first_row_summary(
    table: pd.DataFrame,
    *,
    title: str | None = None,
    columns: Sequence[str] | None = None,
    labels: Mapping[str, str] | None = None,
    units: Mapping[str, str] | None = None,
    formats: Mapping[str, Formatter] | None = None,
    prefix: str = "First-row finding",
) -> str:
    """Describe the first row using only values computed in ``table``."""

    del title
    labels = dict(labels or {})
    units = dict(units or {})
    formats = dict(formats or {})
    selected = list(table.columns if columns is None else columns)
    _require_columns(table, selected)
    if not selected:
        return f"**{prefix}.** No fields were selected."
    if table.empty:
        return f"**{prefix}.** The table contains no rows."

    row = table.iloc[0]
    fields: list[tuple[str, str]] = []
    for column in selected:
        label = labels.get(column, _humanise(column))
        value = _format_value(row[column], formats.get(column))
        if column in units and value != "not available":
            value = f"{value} {units[column]}"
        fields.append((label, _escape_inline(value)))
    if len(fields) == 1:
        label, value = fields[0]
        return f"**{prefix}.** {_upper_initial(label)} is **{value}**."
    subject = fields[0][1]
    predicates = [
        f"{_lower_initial(label)} is **{value}**" for label, value in fields[1:]
    ]
    return f"**{prefix}.** For **{subject}**, {_join(predicates)}."


def _format_value(value: Any, formatter: Formatter | None = None) -> str:
    if pd.api.types.is_scalar(value) and pd.isna(value):
        return "not available"
    if formatter is not None:
        return str(
            formatter(value) if callable(formatter) else format(value, formatter)
        )
    if isinstance(value, pd.Timestamp):
        return (
            value.date().isoformat()
            if value == value.normalize()
            else value.isoformat()
        )
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _escape_cell(value: str) -> str:
    text = html_escape(str(value), quote=False)
    for character in ("\\", "|", "$", "*", "_", "~", "`", "[", "]"):
        text = text.replace(character, f"\\{character}")
    return text


def _escape_inline(value: str) -> str:
    text = str(value)
    for character in ("\\", "$", "*", "_", "~", "`", "[", "]", "<", ">"):
        text = text.replace(character, f"\\{character}")
    return text


def _humanise(name: str) -> str:
    return str(name).replace("_", " ").strip()


def _lower_initial(value: str) -> str:
    return value[:1].lower() + value[1:]


def _upper_initial(value: str) -> str:
    return value[:1].upper() + value[1:]


def _require_columns(table: pd.DataFrame, columns: Sequence[str]) -> None:
    unknown = [column for column in columns if column not in table.columns]
    if unknown:
        raise KeyError(f"Columns are not present in the DataFrame: {unknown}")


def _require_known_keys(
    name: str, values: Mapping[str, Any], columns: Sequence[str]
) -> None:
    unknown = [column for column in values if column not in columns]
    if unknown:
        raise KeyError(f"{name} contains columns not selected for display: {unknown}")


def _join(fields: Sequence[str]) -> str:
    if not fields:
        return "no selected fields"
    if len(fields) == 1:
        return fields[0]
    if len(fields) == 2:
        return f"{fields[0]} and {fields[1]}"
    return ", ".join(fields[:-1]) + f", and {fields[-1]}"
