"""Markdown parser: heading-hierarchy and paragraph-aware extraction.

Markdown has no physical pages, so this parser synthesises a single
retained-extraction "page" row (``physical_page=1``) holding the complete
document text and a structural unit list in ``layout_json``, so a
chunker-only or normalisation-only change can rebuild chunk-input units
without re-reading the file (mirroring the PDF parser's retained-page reuse).
"""

from __future__ import annotations

import json
import re

from .base import ParsedChunkUnit, ParsedPage, ParseResult

NAME = "markdown-heading"
VERSION = "1"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
DEFAULT_MAX_UNIT_CHARS = 2400


def _split_oversized(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    words = text.split(" ")
    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        word_len = len(word) + 1
        if current and current_len + word_len > max_chars:
            parts.append(" ".join(current))
            current = []
            current_len = 0
        current.append(word)
        current_len += word_len
    if current:
        parts.append(" ".join(current))
    return parts


def parse(path, config: dict | None = None) -> ParseResult:
    config = config or {}
    max_unit_chars = int(config.get("max_unit_chars", DEFAULT_MAX_UNIT_CHARS))

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    units: list[ParsedChunkUnit] = []
    heading_path: list[str] = []
    heading_occurrence: dict[str, int] = {}
    heading_key = "root#0"
    para_index = 0
    para_lines: list[str] = []
    para_start_line: int | None = None

    def flush_paragraph(end_line: int) -> None:
        nonlocal para_lines, para_start_line, para_index
        if not para_lines:
            return
        body = "\n".join(para_lines).strip()
        para_lines = []
        start_line = para_start_line
        para_start_line = None
        if not body:
            return
        for sub_index, sub_body in enumerate(_split_oversized(body, max_unit_chars)):
            key = f"{heading_key}:p{para_index:04d}"
            if sub_index:
                key = f"{key}:sub{sub_index:02d}"
            units.append(
                ParsedChunkUnit(
                    text=sub_body,
                    logical_key=key,
                    heading_path=list(heading_path),
                    symbol=None,
                    content_type="body",
                    physical_page=None,
                    line_start=start_line,
                    line_end=end_line,
                    locator={},
                )
            )
            para_index += 1

    for line_no, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        heading_match = _HEADING_RE.match(raw_line)
        if heading_match:
            flush_paragraph(line_no - 1)
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            heading_path = heading_path[: level - 1] + [title]
            key_base = "/".join(heading_path)
            occurrence = heading_occurrence.get(key_base, 0)
            heading_occurrence[key_base] = occurrence + 1
            heading_key = f"{key_base}#{occurrence}"
            para_index = 0
            units.append(
                ParsedChunkUnit(
                    text=title,
                    logical_key=f"{heading_key}:heading",
                    heading_path=list(heading_path),
                    symbol=None,
                    content_type="heading",
                    physical_page=None,
                    line_start=line_no,
                    line_end=line_no,
                    locator={},
                )
            )
            continue
        if not stripped:
            flush_paragraph(line_no - 1)
            continue
        if para_start_line is None:
            para_start_line = line_no
        para_lines.append(raw_line)
    flush_paragraph(len(lines))

    layout_units = [
        {
            "text": unit.text,
            "logical_key": unit.logical_key,
            "heading_path": unit.heading_path,
            "content_type": unit.content_type,
            "line_start": unit.line_start,
            "line_end": unit.line_end,
        }
        for unit in units
    ]

    page = ParsedPage(
        physical_page=1,
        printed_label=None,
        text=text,
        extraction_method=NAME,
        extraction_status="ok" if units else "empty",
        section_candidates=[u.text for u in units if u.content_type == "heading"],
        layout={"units": layout_units},
    )
    return ParseResult(pages=[page], units=units, assets=[])


def units_from_page_layout(layout_json: str) -> list[ParsedChunkUnit]:
    layout = json.loads(layout_json) if layout_json else {"units": []}
    units: list[ParsedChunkUnit] = []
    for entry in layout.get("units", []):
        units.append(
            ParsedChunkUnit(
                text=entry["text"],
                logical_key=entry["logical_key"],
                heading_path=entry["heading_path"],
                symbol=None,
                content_type=entry["content_type"],
                physical_page=None,
                line_start=entry.get("line_start"),
                line_end=entry.get("line_end"),
                locator={},
            )
        )
    return units
