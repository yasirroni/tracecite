"""OOXML workbook parser with worksheet- and A1-range-aware locators.

The parser reads ``.xlsx`` and ``.xlsm`` packages directly with the Python
standard library. It does not execute macros, refresh external connections,
or recalculate formulae. Formula cells retain both the stored formula and any
cached value present in the workbook package.

Each non-empty worksheet row becomes one or more chunk-input units. Style-only
empty cells are ignored, which is important for workbooks whose declared used
range extends to Excel's maximum row or column even though only a small subset
contains values.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

from .base import ParsedChunkUnit, ParsedPage, ParseResult


NAME = "workbook-ooxml"
VERSION = "1"
DEFAULT_MAX_UNIT_CHARS = 1000
DEFAULT_MAX_FORMULA_CHARS = 240

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_WORKSHEET_REL_SUFFIX = "/worksheet"
_CELL_REF_RE = re.compile(r"^([A-Z]+)([0-9]+)$")


@dataclass(frozen=True)
class _Sheet:
    index: int
    name: str
    state: str
    part: str


@dataclass(frozen=True)
class _Cell:
    reference: str
    rendered: str


def _tag(name: str) -> str:
    return f"{{{_MAIN_NS}}}{name}"


def _normalise_part(base_part: str, target: str) -> str:
    target = target.replace("\\", "/")
    if target.startswith("/"):
        resolved = posixpath.normpath(target.lstrip("/"))
    else:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))
    if resolved == ".." or resolved.startswith("../"):
        raise ValueError(f"workbook relationship escapes the OOXML package: {target}")
    return resolved


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    part = "xl/sharedStrings.xml"
    if part not in archive.namelist():
        return []
    strings: list[str] = []
    with archive.open(part) as handle:
        for _event, element in ET.iterparse(handle, events=("end",)):
            if element.tag != _tag("si"):
                continue
            strings.append("".join(node.text or "" for node in element.iter(_tag("t"))))
            element.clear()
    return strings


def _sheets(archive: zipfile.ZipFile) -> list[_Sheet]:
    workbook_part = "xl/workbook.xml"
    relationships_part = "xl/_rels/workbook.xml.rels"
    workbook = ET.fromstring(archive.read(workbook_part))
    relationships = ET.fromstring(archive.read(relationships_part))
    targets: dict[str, tuple[str, str | None]] = {}
    for relationship in relationships.findall(f"{{{_PACKAGE_REL_NS}}}Relationship"):
        targets[relationship.attrib["Id"]] = (
            relationship.attrib["Target"],
            relationship.attrib.get("Type"),
        )

    sheets: list[_Sheet] = []
    for index, sheet in enumerate(workbook.findall(f".//{{{_MAIN_NS}}}sheet"), start=1):
        relationship_id = sheet.attrib[f"{{{_OFFICE_REL_NS}}}id"]
        target, relationship_type = targets[relationship_id]
        if relationship_type and not relationship_type.endswith(_WORKSHEET_REL_SUFFIX):
            continue
        sheets.append(
            _Sheet(
                index=index,
                name=sheet.attrib["name"],
                state=sheet.attrib.get("state", "visible"),
                part=_normalise_part(workbook_part, target),
            )
        )
    return sheets


def _inline_string(cell: ET.Element) -> str:
    inline = cell.find(_tag("is"))
    if inline is None:
        return ""
    return "".join(node.text or "" for node in inline.iter(_tag("t")))


def _stored_value(cell: ET.Element, shared_strings: list[str]) -> tuple[str, bool]:
    cell_type = cell.attrib.get("t")
    value_element = cell.find(_tag("v"))
    raw = value_element.text if value_element is not None and value_element.text is not None else ""

    if cell_type == "inlineStr":
        value = _inline_string(cell)
        return value, True
    if cell_type == "s":
        if raw == "":
            return "", True
        try:
            return shared_strings[int(raw)], True
        except (ValueError, IndexError) as exc:
            raise ValueError(f"invalid shared-string index: {raw}") from exc
    if cell_type == "b":
        return ("TRUE" if raw == "1" else "FALSE"), False
    if cell_type == "e":
        return f"#ERROR {raw}", True
    if cell_type in {"str", "d"}:
        return raw, True
    return raw, False


def _render_cell(
    cell: ET.Element,
    shared_strings: list[str],
    *,
    max_formula_chars: int,
) -> _Cell | None:
    reference = cell.attrib.get("r")
    if not reference or _CELL_REF_RE.fullmatch(reference) is None:
        return None

    formula_element = cell.find(_tag("f"))
    formula = formula_element.text if formula_element is not None else None
    value, is_text = _stored_value(cell, shared_strings)
    if formula is None and value == "":
        return None

    if formula is not None:
        original_formula_length = len(formula)
        if original_formula_length > max_formula_chars:
            formula = (
                formula[:max_formula_chars]
                + f"… [truncated; {original_formula_length} characters]"
            )
        rendered_formula = json.dumps(f"={formula}", ensure_ascii=False)
        if value == "":
            rendered = f"FORMULA {rendered_formula}"
        else:
            cached = json.dumps(value, ensure_ascii=False) if is_text else value
            rendered = f"FORMULA {rendered_formula}; cached = {cached}"
    else:
        rendered = json.dumps(value, ensure_ascii=False) if is_text else value
    return _Cell(reference=reference, rendered=rendered)


def _row_number(row: ET.Element, cells: list[_Cell], fallback: int) -> int:
    declared = row.attrib.get("r")
    if declared and declared.isdigit():
        return int(declared)
    if cells:
        match = _CELL_REF_RE.fullmatch(cells[0].reference)
        if match is not None:
            return int(match.group(2))
    return fallback


def _unit_text(sheet: _Sheet, row_number: int, cells: list[_Cell]) -> str:
    cell_range = cells[0].reference if len(cells) == 1 else f"{cells[0].reference}:{cells[-1].reference}"
    heading = f'Worksheet {json.dumps(sheet.name, ensure_ascii=False)}, row {row_number}, cells {cell_range}'
    values = "\n".join(f"{cell.reference} = {cell.rendered}" for cell in cells)
    return f"{heading}\n{values}"


def _split_row(sheet: _Sheet, row_number: int, cells: list[_Cell], max_unit_chars: int) -> list[list[_Cell]]:
    parts: list[list[_Cell]] = []
    current: list[_Cell] = []
    for cell in cells:
        candidate = current + [cell]
        if current and len(_unit_text(sheet, row_number, candidate)) > max_unit_chars:
            parts.append(current)
            current = [cell]
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _sheet_units(
    archive: zipfile.ZipFile,
    sheet: _Sheet,
    shared_strings: list[str],
    *,
    max_unit_chars: int,
    max_formula_chars: int,
) -> list[ParsedChunkUnit]:
    units: list[ParsedChunkUnit] = []
    fallback_row = 0
    with archive.open(sheet.part) as handle:
        for _event, row in ET.iterparse(handle, events=("end",)):
            if row.tag != _tag("row"):
                continue
            fallback_row += 1
            cells = [
                parsed
                for cell in row.findall(_tag("c"))
                if (
                    parsed := _render_cell(
                        cell,
                        shared_strings,
                        max_formula_chars=max_formula_chars,
                    )
                )
                is not None
            ]
            if cells:
                row_number = _row_number(row, cells, fallback_row)
                for part_index, part in enumerate(
                    _split_row(sheet, row_number, cells, max_unit_chars), start=1
                ):
                    start_cell = part[0].reference
                    end_cell = part[-1].reference
                    cell_range = start_cell if start_cell == end_cell else f"{start_cell}:{end_cell}"
                    units.append(
                        ParsedChunkUnit(
                            text=_unit_text(sheet, row_number, part),
                            logical_key=(
                                f"sheet:{sheet.index:04d}:row:{row_number:07d}:part:{part_index:04d}"
                            ),
                            heading_path=[sheet.name],
                            symbol=None,
                            content_type="workbook-row",
                            physical_page=None,
                            locator={
                                "kind": "excel-range",
                                "sheet": sheet.name,
                                "sheet_index": sheet.index,
                                "sheet_state": sheet.state,
                                "range": cell_range,
                                "start_cell": start_cell,
                                "end_cell": end_cell,
                                "row_start": row_number,
                                "row_end": row_number,
                            },
                        )
                    )
            row.clear()
    return units


def parse(path: Path, config: dict | None = None) -> ParseResult:
    config = config or {}
    max_unit_chars = int(config.get("max_unit_chars", DEFAULT_MAX_UNIT_CHARS))
    max_formula_chars = int(config.get("max_formula_chars", DEFAULT_MAX_FORMULA_CHARS))
    if max_unit_chars <= 0:
        raise ValueError("max_unit_chars must be positive")
    if max_formula_chars <= 0:
        raise ValueError("max_formula_chars must be positive")

    pages: list[ParsedPage] = []
    units: list[ParsedChunkUnit] = []
    with zipfile.ZipFile(path) as archive:
        shared_strings = _shared_strings(archive)
        for sheet in _sheets(archive):
            sheet_units = _sheet_units(
                archive,
                sheet,
                shared_strings,
                max_unit_chars=max_unit_chars,
                max_formula_chars=max_formula_chars,
            )
            units.extend(sheet_units)
            layout_units = [
                {
                    "text": unit.text,
                    "logical_key": unit.logical_key,
                    "heading_path": unit.heading_path,
                    "content_type": unit.content_type,
                    "locator": unit.locator,
                }
                for unit in sheet_units
            ]
            pages.append(
                ParsedPage(
                    physical_page=sheet.index,
                    printed_label=sheet.name,
                    text="\n\n".join(unit.text for unit in sheet_units),
                    extraction_method=NAME,
                    extraction_status="ok" if sheet_units else "empty",
                    section_candidates=[sheet.name],
                    layout={
                        "kind": "workbook-sheet",
                        "sheet": sheet.name,
                        "sheet_index": sheet.index,
                        "sheet_state": sheet.state,
                        "units": layout_units,
                    },
                )
            )
    return ParseResult(pages=pages, units=units, assets=[])


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
                locator=entry.get("locator", {}),
            )
        )
    return units