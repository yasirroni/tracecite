"""Pandoc-backed parsing for native Markdown tables."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
from typing import Any, Iterable

from ._text import collapse_space, strip_caption_id, strip_html
from .models import TableDiagnostic, TableNormalisationError


@dataclass(slots=True)
class ParsedPandocTable:
    table_id: str | None
    caption: str | None
    headers: list[str]
    rows: list[list[str]]
    alignments: list[str]
    diagnostics: list[TableDiagnostic]
    attributes: dict[str, str]


def resolve_pandoc(explicit: str | Path | None = None) -> list[str]:
    """Resolve standalone Pandoc or Quarto's bundled Pandoc."""

    configured = explicit or os.getenv("TRACECITE_PANDOC")
    if configured:
        command = shlex.split(str(configured))
        if command and shutil.which(command[0]):
            return command
        path = Path(str(configured))
        if path.is_file():
            return [str(path)]
        raise FileNotFoundError(
            f"Configured Pandoc command is unavailable: {configured}"
        )

    quarto = shutil.which("quarto")
    if quarto:
        return [quarto, "pandoc"]

    pandoc = shutil.which("pandoc")
    if pandoc:
        return [pandoc]

    raise FileNotFoundError(
        "Pandoc is required for full table normalisation. Install Pandoc or Quarto, "
        "or configure TRACECITE_PANDOC."
    )


def markdown_to_ast(
    markdown: str,
    *,
    pandoc: str | Path | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    command = [
        *resolve_pandoc(pandoc),
        "--from=markdown+pipe_tables+grid_tables+multiline_tables+table_captions+raw_html",
        "--to=json",
    ]
    completed = subprocess.run(
        command,
        input=markdown,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        message = (
            completed.stderr.strip() or completed.stdout.strip() or "Pandoc failed"
        )
        raise TableNormalisationError(message)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise TableNormalisationError("Pandoc returned invalid JSON") from error


def parse_pandoc_tables(
    markdown: str,
    *,
    pandoc: str | Path | None = None,
) -> list[ParsedPandocTable]:
    ast = markdown_to_ast(markdown, pandoc=pandoc)
    return [
        parse_table_node(node) for node in _walk_nodes(ast) if node.get("t") == "Table"
    ]


def parse_table_node(node: dict[str, Any]) -> ParsedPandocTable:
    try:
        attr, caption_value, colspecs, head, bodies, foot = node["c"]
    except (KeyError, TypeError, ValueError) as error:
        raise TableNormalisationError("Unsupported Pandoc Table AST shape") from error

    diagnostics: list[TableDiagnostic] = []
    table_id, classes, key_values = _attr(attr)
    attributes = {key: value for key, value in key_values}
    if classes:
        attributes["classes"] = " ".join(classes)

    caption = _caption_text(caption_value)
    caption, caption_id = strip_caption_id(caption or "")
    if not table_id:
        table_id = caption_id
    caption = caption or None

    alignments = [_alignment(spec[0]) for spec in colspecs]
    ncols = len(colspecs)

    header_rows = _rows_from_section(head)
    expanded_headers = _expand_rows(header_rows, ncols, diagnostics, section="header")
    if not ncols:
        ncols = max((len(row) for row in expanded_headers), default=0)

    body_rows: list[list[Any]] = []
    for body in bodies:
        try:
            _body_attr, row_head_columns, intermediate_heads, rows = body
        except (TypeError, ValueError) as error:
            raise TableNormalisationError(
                "Unsupported Pandoc table body shape"
            ) from error
        if row_head_columns:
            diagnostics.append(
                TableDiagnostic(
                    "table.row-head-columns",
                    "info",
                    f"Pandoc marks {row_head_columns} body column(s) as row headers.",
                )
            )
        if intermediate_heads:
            diagnostics.append(
                TableDiagnostic(
                    "table.intermediate-headers",
                    "warning",
                    "Intermediate body headers were flattened into ordinary rows.",
                )
            )
            body_rows.extend(intermediate_heads)
        body_rows.extend(rows)

    expanded_rows = _expand_rows(body_rows, ncols, diagnostics, section="body")
    foot_rows = _rows_from_section(foot)
    if foot_rows:
        diagnostics.append(
            TableDiagnostic(
                "table.footer-rows",
                "warning",
                "Footer rows were appended to the normalised body.",
            )
        )
        expanded_rows.extend(
            _expand_rows(foot_rows, ncols, diagnostics, section="footer")
        )

    headers = _combine_header_rows(expanded_headers, ncols)
    if not headers:
        headers = [f"Column {index}" for index in range(1, ncols + 1)]
    if all(not value for value in headers):
        headers = [f"Column {index}" for index in range(1, ncols + 1)]
        diagnostics.append(
            TableDiagnostic(
                "table.generated-headers",
                "warning",
                "The source table had no usable headers; deterministic column names were generated.",
            )
        )
    else:
        for index, value in enumerate(headers):
            if not value:
                headers[index] = f"Column {index + 1}"
                diagnostics.append(
                    TableDiagnostic(
                        "table.empty-header",
                        "warning",
                        f"Header {index + 1} was empty and was replaced by a deterministic name.",
                        column=index + 1,
                    )
                )

    if len(alignments) < len(headers):
        alignments.extend(["default"] * (len(headers) - len(alignments)))

    return ParsedPandocTable(
        table_id=table_id or None,
        caption=caption,
        headers=headers,
        rows=[_fit_width(row, len(headers)) for row in expanded_rows],
        alignments=alignments[: len(headers)],
        diagnostics=diagnostics,
        attributes=attributes,
    )


def ast_tables_with_sections(
    markdown: str,
    *,
    pandoc: str | Path | None = None,
) -> list[tuple[tuple[str, ...], ParsedPandocTable]]:
    """Return every Pandoc table with the heading path active at that node."""

    ast = markdown_to_ast(markdown, pandoc=pandoc)
    headings: list[str] = []
    result: list[tuple[tuple[str, ...], ParsedPandocTable]] = []

    def visit_blocks(blocks: Iterable[dict[str, Any]]) -> None:
        nonlocal headings
        for block in blocks:
            kind = block.get("t")
            if kind == "Header":
                level, _attr_value, inlines = block["c"]
                title = _inlines_text(inlines)
                headings = headings[: max(0, level - 1)]
                while len(headings) < level - 1:
                    headings.append("")
                headings.append(title)
            elif kind == "Table":
                result.append(
                    (tuple(item for item in headings if item), parse_table_node(block))
                )
            else:
                for nested in _nested_block_lists(block):
                    visit_blocks(nested)

    visit_blocks(ast.get("blocks", []))
    return result


def _walk_nodes(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_nodes(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_nodes(item)


def _nested_block_lists(node: dict[str, Any]) -> Iterable[list[dict[str, Any]]]:
    kind = node.get("t")
    value = node.get("c")
    if kind == "Div" and isinstance(value, list) and len(value) == 2:
        yield value[1]
    elif kind in {"BlockQuote"} and isinstance(value, list):
        yield value
    elif kind in {"BulletList", "OrderedList"}:
        items = value if kind == "BulletList" else value[1]
        for item in items:
            yield item
    elif kind == "DefinitionList":
        for _term, definitions in value:
            for definition in definitions:
                yield definition


def _attr(value: Any) -> tuple[str, list[str], list[tuple[str, str]]]:
    if not isinstance(value, list) or len(value) != 3:
        return "", [], []
    identifier, classes, key_values = value
    return (
        str(identifier),
        [str(item) for item in classes],
        [(str(key), str(item)) for key, item in key_values],
    )


def _caption_text(value: Any) -> str:
    if not isinstance(value, list) or len(value) != 2:
        return ""
    short, blocks = value
    if short:
        return _inlines_text(short)
    return _blocks_text(blocks)


def _rows_from_section(value: Any) -> list[Any]:
    if not isinstance(value, list) or len(value) != 2:
        return []
    return list(value[1])


def _expand_rows(
    rows: list[Any],
    ncols: int,
    diagnostics: list[TableDiagnostic],
    *,
    section: str,
) -> list[list[str]]:
    if not rows:
        return []

    if not ncols:
        ncols = max(
            (
                sum(max(1, int(cell[3])) for cell in row[1])
                for row in rows
                if isinstance(row, list) and len(row) == 2
            ),
            default=0,
        )

    pending: dict[int, tuple[int, str]] = {}
    expanded: list[list[str]] = []
    for row_index, row in enumerate(rows, start=1):
        cells = row[1] if isinstance(row, list) and len(row) == 2 else []
        values: list[str | None] = [None] * ncols

        for column, (remaining, text) in list(pending.items()):
            if column < ncols:
                values[column] = text
            if remaining <= 1:
                del pending[column]
            else:
                pending[column] = (remaining - 1, text)

        cursor = 0
        for cell in cells:
            while cursor < ncols and values[cursor] is not None:
                cursor += 1
            if cursor >= ncols:
                diagnostics.append(
                    TableDiagnostic(
                        "table.extra-cell",
                        "error",
                        f"A {section} row contains more logical cells than the declared width.",
                        row=row_index,
                    )
                )
                break
            try:
                _cell_attr, _cell_align, rowspan, colspan, blocks = cell
            except (TypeError, ValueError):
                diagnostics.append(
                    TableDiagnostic(
                        "table.unsupported-cell",
                        "error",
                        "A Pandoc table cell has an unsupported AST shape.",
                        row=row_index,
                        column=cursor + 1,
                    )
                )
                continue

            rowspan = max(1, int(rowspan))
            colspan = max(1, int(colspan))
            text = _blocks_text(blocks)
            if rowspan > 1 or colspan > 1:
                diagnostics.append(
                    TableDiagnostic(
                        "table.span-expanded",
                        "warning",
                        f"A {rowspan}x{colspan} cell span was expanded by repeating its visible value.",
                        row=row_index,
                        column=cursor + 1,
                    )
                )

            for offset in range(colspan):
                column = cursor + offset
                if column >= ncols:
                    diagnostics.append(
                        TableDiagnostic(
                            "table.span-overflow",
                            "error",
                            "A cell span exceeds the declared table width.",
                            row=row_index,
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
                "A row span extends beyond the final row in its table section.",
            )
        )
    return expanded


def _combine_header_rows(rows: list[list[str]], ncols: int) -> list[str]:
    if not rows or not ncols:
        return []
    combined: list[str] = []
    for column in range(ncols):
        values: list[str] = []
        for row in rows:
            value = collapse_space(row[column] if column < len(row) else "")
            if value and value not in values:
                values.append(value)
        combined.append(" / ".join(values))
    return combined


def _fit_width(row: list[str], width: int) -> list[str]:
    if len(row) < width:
        return [*row, *([""] * (width - len(row)))]
    return row[:width]


def _alignment(value: Any) -> str:
    if isinstance(value, dict):
        name = value.get("t", "AlignDefault")
    else:
        name = str(value)
    return {
        "AlignLeft": "left",
        "AlignCenter": "center",
        "AlignRight": "right",
    }.get(name, "default")


def _blocks_text(blocks: Any) -> str:
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.get("t")
        value = block.get("c")
        if kind in {"Plain", "Para", "Header"}:
            inlines = value if kind != "Header" else value[2]
            parts.append(_inlines_text(inlines))
        elif kind == "CodeBlock":
            parts.append(f"`{value[1]}`")
        elif kind == "RawBlock":
            fmt, raw = value
            parts.append(strip_html(raw) if fmt == "html" else str(raw))
        elif kind == "BlockQuote":
            parts.append(_blocks_text(value))
        elif kind == "BulletList":
            parts.append("; ".join(_blocks_text(item) for item in value))
        elif kind == "OrderedList":
            parts.append("; ".join(_blocks_text(item) for item in value[1]))
        elif kind == "DefinitionList":
            for term, definitions in value:
                definition = "; ".join(_blocks_text(item) for item in definitions)
                parts.append(f"{_inlines_text(term)}: {definition}")
        elif kind == "Div":
            parts.append(_blocks_text(value[1]))
        elif kind == "HorizontalRule":
            parts.append("—")
    return collapse_space(" ".join(item for item in parts if item))


def _inlines_text(inlines: Any) -> str:
    if not isinstance(inlines, list):
        return ""
    parts: list[str] = []
    for inline in inlines:
        if not isinstance(inline, dict):
            continue
        kind = inline.get("t")
        value = inline.get("c")
        if kind == "Str":
            parts.append(str(value))
        elif kind in {"Space", "SoftBreak", "LineBreak"}:
            parts.append(" ")
        elif kind == "Code":
            parts.append(f"`{value[1]}`")
        elif kind == "Math":
            parts.append(f"${value[1]}$")
        elif kind in {
            "Emph",
            "Strong",
            "Strikeout",
            "Superscript",
            "Subscript",
            "SmallCaps",
            "Underline",
        }:
            parts.append(_inlines_text(value))
        elif kind == "Quoted":
            parts.append(_inlines_text(value[1]))
        elif kind in {"Span", "Cite"}:
            nested = value[1]
            parts.append(_inlines_text(nested))
        elif kind == "Link":
            label = _inlines_text(value[1])
            target = value[2][0]
            parts.append(f"{label} ({target})" if target else label)
        elif kind == "Image":
            label = _inlines_text(value[1]) or "image"
            target = value[2][0]
            parts.append(f"{label} ({target})" if target else label)
        elif kind == "RawInline":
            fmt, raw = value
            parts.append(strip_html(raw) if fmt == "html" else str(raw))
        elif kind == "Note":
            parts.append(_blocks_text(value))
    return collapse_space("".join(parts))
