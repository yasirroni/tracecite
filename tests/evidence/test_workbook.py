"""Workbook parser, synchronisation, and retrieval contract tests."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from conftest import build_markdown, write_manifest

from tracecite.evidence import chunking, schema
from tracecite.evidence import sync as sync_module
from tracecite.evidence.commands import cmd_page, hybrid_search
from tracecite.evidence.parsers import workbook as workbook_parser
from tracecite.evidence.parsers.base import units_from_layout


def _write_test_workbook(path: Path, retirement_year: int = 2035) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = {
        "xl/workbook.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Retirement assumptions" sheetId="1" r:id="rId1"/></sheets>
</workbook>
""",
        "xl/_rels/workbook.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet1.xml"/>
</Relationships>
""",
        "xl/sharedStrings.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="3" uniqueCount="3">
  <si><t>Technology</t></si>
  <si><t>Brown coal</t></si>
  <si><r><t>Retirement </t></r><r><t>year</t></r></si>
</sst>
""",
        "xl/worksheets/sheet1.xml": f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="s"><v>0</v></c>
      <c r="B1" t="s"><v>2</v></c>
    </row>
    <row r="2">
      <c r="A2" t="s"><v>1</v></c>
      <c r="B2"><v>{retirement_year}</v></c>
      <c r="C2"><f>B2+5</f><v>2040</v></c>
    </row>
    <row r="3">
      <c r="A3" t="inlineStr"><is><t>Formula without cached value</t></is></c>
      <c r="B3"><f>SUM(B2,1234567890)</f></c>
    </row>
    <row r="1048576"><c r="XFD1048576" s="1"/></row>
  </sheetData>
</worksheet>
""",
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return path


def test_workbook_parser_retains_sheet_ranges_values_and_formula_status(tmp_path: Path):
    path = _write_test_workbook(tmp_path / "assumptions.xlsx")
    result = workbook_parser.parse(path, {"max_formula_chars": 10})

    assert len(result.pages) == 1
    assert result.pages[0].printed_label == "Retirement assumptions"
    assert result.pages[0].extraction_status == "ok"
    assert len(result.units) == 3
    assert "Retirement year" in result.units[0].text
    assert 'A2 = "Brown coal"' in result.units[1].text
    assert "B2 = 2035" in result.units[1].text
    assert 'C2 = FORMULA "=B2+5"; cached = 2040' in result.units[1].text
    assert "truncated" in result.units[2].text
    assert result.units[1].locator == {
        "kind": "excel-range",
        "sheet": "Retirement assumptions",
        "sheet_index": 1,
        "sheet_state": "visible",
        "range": "A2:C2",
        "start_cell": "A2",
        "end_cell": "C2",
        "row_start": 2,
        "row_end": 2,
    }

    rebuilt = units_from_layout(json.dumps(result.pages[0].layout))
    assert rebuilt == result.units


def test_workbook_chunk_locator_merges_adjacent_row_ranges(tmp_path: Path):
    result = workbook_parser.parse(_write_test_workbook(tmp_path / "assumptions.xlsm"))
    groups = chunking.group_units(result.units, max_chars=10_000)
    candidates = chunking.build_chunk_candidates(
        groups,
        source_type="workbook",
        normalisation_version=schema.NORMALISATION_VERSION,
    )
    assert len(candidates) == 1
    assert candidates[0].locator["sheet"] == "Retirement assumptions"
    assert candidates[0].locator["range"] == "A1:C3"
    assert candidates[0].locator["range_kind"] == "bounding"
    assert candidates[0].locator["exact_ranges"] == ["A1:B1", "A2:C2", "A3:B3"]
    assert candidates[0].locator["row_start"] == 1
    assert candidates[0].locator["row_end"] == 3


def test_workbook_sync_and_search_expose_defensible_locator(
    corpus_dir,
    manifest_path,
    database_path,
    make_embedder,
):
    workbook_path = _write_test_workbook(corpus_dir / "assumptions.xlsx")
    write_manifest(manifest_path, {workbook_path.name: workbook_path.name})
    embedder = make_embedder()

    report = sync_module.sync(
        corpus_dir,
        manifest_path,
        database_path,
        embedder=embedder,
    )
    assert report.sources_added == ["assumptions.xlsx"]

    conn = schema.connect(database_path)
    try:
        results = hybrid_search(conn, "brown coal retirement year", 5, 50, 50, embedder)
        assert results
        result = results[0]
        assert result["source_path"] == "assumptions.xlsx"
        assert result["source_type"] == "workbook"
        assert len(result["source_sha256"]) == 64
        assert result["locator"]["sheet"] == "Retirement assumptions"
        assert result["locator"]["range"] == "A1:C3"
        assert result["locator"]["range_kind"] == "bounding"
        assert result["locator"]["exact_ranges"] == ["A1:B1", "A2:C2", "A3:B3"]
        assert result["physical_page"] is None
        assert "pdf_link" not in result
    finally:
        conn.close()


def test_page_command_rejects_workbook_sheet_indexes_as_pdf_pages(
    corpus_dir,
    manifest_path,
    database_path,
    make_embedder,
    capsys,
):
    workbook_path = _write_test_workbook(corpus_dir / "assumptions.xlsx")
    write_manifest(manifest_path, {workbook_path.name: workbook_path.name})
    sync_module.sync(
        corpus_dir,
        manifest_path,
        database_path,
        embedder=make_embedder(),
    )

    status = cmd_page(
        SimpleNamespace(
            database=database_path,
            root=corpus_dir,
            source_path=workbook_path.name,
            page=None,
            format="json",
        )
    )

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert captured.err == "source is not a pdf: assumptions.xlsx\n"


def test_workbook_dropped_from_manifest_is_retained_until_prune(
    corpus_dir,
    manifest_path,
    database_path,
    make_embedder,
):
    workbook_path = _write_test_workbook(corpus_dir / "assumptions.xlsx")
    notes_path = build_markdown(
        corpus_dir / "notes.md", "# Notes\n\nA Markdown source that stays selected.\n"
    )
    write_manifest(
        manifest_path, {"workbook": workbook_path.name, "notes": notes_path.name}
    )
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)

    write_manifest(manifest_path, {"notes": notes_path.name})
    report = sync_module.sync(
        corpus_dir, manifest_path, database_path, embedder=embedder
    )
    assert report.indexed_unselected_paths == ["assumptions.xlsx"]
    assert report.selected_missing_paths == []

    conn = schema.connect(database_path)
    try:
        workbook_chunks = "SELECT count(*) FROM chunks JOIN sources USING (source_pk) WHERE sources.path = 'assumptions.xlsx'"
        assert conn.execute(workbook_chunks).fetchone()[0] > 0

        plan = sync_module.plan_prune(conn, selected_paths=["notes.md"])
        assert plan.paths == ("assumptions.xlsx",)
        assert sync_module.apply_prune(conn, database_path, plan) == []
        assert {row["path"] for row in conn.execute("SELECT path FROM sources")} == {
            "notes.md"
        }
        assert conn.execute(workbook_chunks).fetchone()[0] == 0
        assert sync_module.integrity_check(conn) == []
    finally:
        conn.close()


def test_workbook_cell_change_reparses_and_replaces_searchable_chunks(
    corpus_dir,
    manifest_path,
    database_path,
    make_embedder,
):
    workbook_path = _write_test_workbook(corpus_dir / "assumptions.xlsx")
    write_manifest(manifest_path, {workbook_path.name: workbook_path.name})
    embedder = make_embedder()
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)

    _write_test_workbook(workbook_path, retirement_year=2031)
    report = sync_module.sync(
        corpus_dir, manifest_path, database_path, embedder=embedder
    )
    assert report.sources_reparsed == ["assumptions.xlsx"]

    conn = schema.connect(database_path)
    try:
        body = "\n".join(row["body"] for row in conn.execute("SELECT body FROM chunks"))
        assert "B2 = 2031" in body
        assert "B2 = 2035" not in body

        results = hybrid_search(conn, "brown coal retirement year", 5, 50, 50, embedder)
        assert results[0]["source_path"] == "assumptions.xlsx"
        assert "B2 = 2031" in results[0]["passage"]
        assert sync_module.integrity_check(conn) == []
    finally:
        conn.close()
