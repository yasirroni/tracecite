"""HTML-table adapter for Literate.jl, Documenter.jl, and HTML MIME output."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

from ._text import collapse_space, escape_pipe_cell
from .models import (
    NormalisedTable,
    TableContext,
    TableDiagnostic,
    TableNormalisationError,
    source_hash,
)
from .normalise import normalise_pandoc_table


def html_table_to_markdown(
    source: str,
    *,
    context: TableContext | None = None,
) -> tuple[str, tuple[TableDiagnostic, ...]]:
    """Convert exactly one top-level HTML table to canonical pipe Markdown."""

    context = context or TableContext()
    soup = BeautifulSoup(source, "html.parser")
    tables = [
        table for table in soup.find_all("table") if table.find_parent("table") is None
    ]
    if len(tables) != 1:
        raise TableNormalisationError(
            f"html_table_to_markdown expects exactly one top-level table; found {len(tables)}"
        )

    table = tables[0]
    diagnostics: list[TableDiagnostic] = []
    if table.find("table") is not None:
        diagnostics.append(
            TableDiagnostic(
                "table.unsupported-nested-table",
                "error",
                "Nested HTML tables are preserved as raw evidence but are not flattened silently.",
            )
        )

    logical_rows = [
        row for row in table.find_all("tr") if row.find_parent("table") is table
    ]
    if not logical_rows:
        raise TableNormalisationError("The HTML table contains no rows")

    width = max(
        (
            sum(_span(cell, "colspan") for cell in _direct_cells(row))
            for row in logical_rows
        ),
        default=0,
    )
    expanded = _expand_html_rows(logical_rows, width, diagnostics)

    thead_rows = {
        index
        for index, row in enumerate(logical_rows)
        if row.find_parent("thead") is not None
    }
    if thead_rows:
        header_indices = sorted(thead_rows)
    else:
        header_indices = []
        for index, row in enumerate(logical_rows):
            cells = _direct_cells(row)
            if cells and all(cell.name == "th" for cell in cells):
                header_indices.append(index)
            else:
                break

    if header_indices:
        header_rows = [expanded[index] for index in header_indices]
        headers = _combine_header_rows(header_rows, width)
        body_rows = [
            row for index, row in enumerate(expanded) if index not in header_indices
        ]
    else:
        headers = [f"Column {index}" for index in range(1, width + 1)]
        body_rows = expanded
        diagnostics.append(
            TableDiagnostic(
                "table.generated-headers",
                "warning",
                "The HTML table had no complete header row; deterministic headers were generated.",
            )
        )

    caption_tag = table.find("caption", recursive=False)
    caption = context.caption or (_render_html(caption_tag) if caption_tag else None)
    table_id = context.table_id or str(table.get("id") or "").strip() or None

    lines = [
        "| " + " | ".join(escape_pipe_cell(value) for value in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(escape_pipe_cell(value) for value in row) + " |"
        for row in body_rows
    )
    if caption:
        suffix = f" {{#{table_id}}}" if table_id else ""
        lines.extend(["", f": {caption}{suffix}"])
    return "\n".join(lines), tuple(diagnostics)


def normalise_html_table(
    source: str,
    *,
    context: TableContext | None = None,
    strict: bool = False,
    pandoc: str | Path | None = None,
) -> NormalisedTable:
    """Normalise one HTML table through the shared Pandoc-table contract."""

    context = context or TableContext()
    soup = BeautifulSoup(source, "html.parser")
    tables = [
        table for table in soup.find_all("table") if table.find_parent("table") is None
    ]
    if len(tables) != 1:
        raise TableNormalisationError(
            f"normalise_html_table expects exactly one top-level table; found {len(tables)}"
        )
    html_table = tables[0]
    caption_tag = html_table.find("caption", recursive=False)
    context = context.merged(
        table_id=context.table_id or str(html_table.get("id") or "").strip() or None,
        caption=context.caption or (_render_html(caption_tag) if caption_tag else None),
    )
    markdown, adapter_diagnostics = html_table_to_markdown(source, context=context)
    result = normalise_pandoc_table(
        markdown,
        context=context,
        strict=False,
        pandoc=pandoc,
        allow_pipe_fallback=True,
    )
    diagnostics = (*adapter_diagnostics, *result.diagnostics)
    supported = result.supported and not any(
        item.code == "table.unsupported-nested-table" for item in diagnostics
    )
    result = replace(
        result,
        raw_source=source,
        source_format="html",
        canonical_markdown=markdown,
        diagnostics=diagnostics,
        source_hash=source_hash(source, context),
        supported=supported,
    )
    if strict and (result.has_errors or not result.supported):
        errors = "; ".join(
            item.message for item in result.diagnostics if item.severity == "error"
        )
        raise TableNormalisationError(
            f"Table {result.table_id} failed strict HTML normalisation: {errors}"
        )
    return result


def _expand_html_rows(
    rows: list[Tag],
    width: int,
    diagnostics: list[TableDiagnostic],
) -> list[list[str]]:
    pending: dict[int, tuple[int, str]] = {}
    expanded: list[list[str]] = []

    for row_number, row in enumerate(rows, start=1):
        values: list[str | None] = [None] * width
        for column, (remaining, text) in list(pending.items()):
            if column < width:
                values[column] = text
            if remaining <= 1:
                del pending[column]
            else:
                pending[column] = (remaining - 1, text)

        cursor = 0
        for cell in _direct_cells(row):
            while cursor < width and values[cursor] is not None:
                cursor += 1
            if cursor >= width:
                diagnostics.append(
                    TableDiagnostic(
                        "table.extra-cell",
                        "error",
                        "An HTML row contains more logical cells than the inferred width.",
                        row=row_number,
                    )
                )
                break

            rowspan = _span(cell, "rowspan")
            colspan = _span(cell, "colspan")
            text = _render_html(cell)
            if rowspan > 1 or colspan > 1:
                diagnostics.append(
                    TableDiagnostic(
                        "table.span-expanded",
                        "warning",
                        f"A {rowspan}x{colspan} HTML cell span was expanded by repeating its visible value.",
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
                            "An HTML cell span exceeds the inferred table width.",
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
                "An HTML row span extends beyond the final table row.",
            )
        )
    return expanded


def _direct_cells(row: Tag) -> list[Tag]:
    return [
        cell
        for cell in row.find_all(["th", "td"], recursive=False)
        if isinstance(cell, Tag)
    ]


def _span(cell: Tag, attribute: str) -> int:
    try:
        return max(1, int(cell.get(attribute, 1)))
    except (TypeError, ValueError):
        return 1


def _combine_header_rows(rows: list[list[str]], width: int) -> list[str]:
    headers = []
    for column in range(width):
        values: list[str] = []
        for row in rows:
            value = collapse_space(row[column] if column < len(row) else "")
            if value and value not in values:
                values.append(value)
        headers.append(" / ".join(values) or f"Column {column + 1}")
    return headers


def _render_html(node: Tag | NavigableString | None) -> str:
    if node is None:
        return ""
    if isinstance(node, NavigableString):
        return collapse_space(str(node))
    if not isinstance(node, Tag):
        return collapse_space(str(node))
    if node.name == "table":
        return "[nested table omitted]"
    if node.name == "br":
        return " "
    if node.name == "a":
        label = collapse_space(" ".join(_render_html(child) for child in node.children))
        href = str(node.get("href") or "").strip()
        return f"{label} ({href})" if href else label
    if node.name == "code":
        return f"`{node.get_text(' ', strip=True)}`"
    if node.name == "img":
        alt = str(node.get("alt") or "image").strip()
        src = str(node.get("src") or "").strip()
        return f"{alt} ({src})" if src else alt

    pieces = [_render_html(child) for child in node.children]
    separator = "; " if node.name in {"ul", "ol", "li"} else " "
    return collapse_space(separator.join(item for item in pieces if item))
