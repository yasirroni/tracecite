from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tracecite import cli
from tracecite.evidence import schema

from conftest import build_pdf


def _insert_pdf_source(database_path: Path, source_path: str, source_pdf: Path, page_count: int) -> None:
    conn = schema.connect(database_path)
    try:
        schema.ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO sources (
                path, source_type, language, canonical_url,
                capture_manifest_ref, sha256, size_bytes, mtime_ns,
                parser_name, parser_version, parser_config,
                chunker_name, chunker_version, chunker_config,
                normalisation_version, normalisation_config,
                indexed_at_utc, index_status
            ) VALUES (?, 'pdf', NULL, NULL, NULL, ?, 1, 1, 'parser', '1', '{}', 'chunker', '1', '{}', '1', '{}', 'now', 'ok')
            """,
            (source_path, hashlib.sha256(source_pdf.read_bytes()).hexdigest()),
        )
        source_pk = conn.execute("SELECT source_pk FROM sources WHERE path = ?", (source_path,)).fetchone()["source_pk"]
        for physical_page in range(1, page_count + 1):
            conn.execute(
                """
                INSERT INTO pages (
                    source_pk, physical_page, printed_label, text,
                    extraction_method, extraction_status, section_candidates, layout_json
                ) VALUES (?, ?, NULL, ?, 'pdf', 'ok', NULL, NULL)
                """,
                (source_pk, physical_page, f"Page {physical_page} text"),
            )
        conn.commit()
    finally:
        conn.close()


def _extract_summary(stdout: str) -> dict:
    return json.loads(stdout)


def _extract_manifest(summary: dict) -> dict:
    return json.loads(Path(summary["manifest_path"]).read_text(encoding="utf-8"))


def test_extract_pages_defaults_to_page_one_and_writes_manifest(corpus_dir, database_path, capsys):
    source_pdf = build_pdf(corpus_dir / "source.pdf", [["Page 1 text"], ["Page 2 text"]])
    source_bytes = source_pdf.read_bytes()
    _insert_pdf_source(database_path, "source.pdf", source_pdf, 2)
    output_dir = database_path.parent / "exports"
    output_dir.mkdir()

    exit_code = cli.main(["extract-pages", "--root", str(corpus_dir), "--database", str(database_path), "source.pdf", "--output-dir", str(output_dir)])
    captured = capsys.readouterr()

    assert exit_code == 0
    summary = _extract_summary(captured.out)
    assert summary["normalized_pages"] == [1]
    assert len(summary["pdf_path"].split("/")[-1]) <= 80
    pdf_path = Path(summary["pdf_path"])
    manifest_path = Path(summary["manifest_path"])
    assert pdf_path.is_file()
    assert manifest_path.is_file()
    manifest = _extract_manifest(summary)
    assert manifest["original_selector"] is None
    assert manifest["selector"] == "1"
    assert manifest["normalized_pages"] == [1]
    assert manifest["page_count"] == 1
    assert manifest["source_page_count"] == 2
    assert manifest["source_path"] == "source.pdf"
    assert manifest["source_sha256"] == hashlib.sha256(source_pdf.read_bytes()).hexdigest()
    assert manifest["derivative_filename"] == pdf_path.name
    assert manifest["derivative_sha256"] == hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    assert source_pdf.read_bytes() == source_bytes


@pytest.mark.parametrize("selector, expected_pages", [("2-3", [2, 3]), ("3-", [3, 4]), ("-2", [1, 2]), ("4,2-3,1", [1, 2, 3, 4]), ("all", [1, 2, 3, 4])])
def test_extract_pages_supports_closed_open_list_and_all(corpus_dir, database_path, selector, expected_pages, capsys):
    source_pdf = build_pdf(corpus_dir / "source.pdf", [["Page 1"], ["Page 2"], ["Page 3"], ["Page 4"]])
    _insert_pdf_source(database_path, "source.pdf", source_pdf, 4)
    output_dir = database_path.parent / "exports"
    output_dir.mkdir()

    exit_code = cli.main(["extract-pages", "--root", str(corpus_dir), "--database", str(database_path), "source.pdf", selector, "--output-dir", str(output_dir)])
    captured = capsys.readouterr()

    assert exit_code == 0
    summary = _extract_summary(captured.out)
    assert summary["normalized_pages"] == expected_pages
    assert summary["pdf_path"]
    assert summary["manifest_path"]
    import fitz

    with fitz.open(summary["pdf_path"]) as derivative:
        assert derivative.page_count == len(expected_pages)
        assert [derivative[index].get_text().strip() for index in range(derivative.page_count)] == [
            f"Page {page}" for page in expected_pages
        ]


def test_extract_pages_rejects_missing_indexed_pages_and_pdf_mismatch(corpus_dir, database_path, capsys):
    source_pdf = build_pdf(corpus_dir / "source.pdf", [["Page 1"], ["Page 2"]])
    _insert_pdf_source(database_path, "source.pdf", source_pdf, 2)
    output_dir = database_path.parent / "exports"
    output_dir.mkdir()

    exit_code = cli.main(["extract-pages", "--root", str(corpus_dir), "--database", str(database_path), "source.pdf", "3", "--output-dir", str(output_dir)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""

    build_pdf(corpus_dir / "source.pdf", [["Page 1"]])
    exit_code = cli.main(["extract-pages", "--root", str(corpus_dir), "--database", str(database_path), "source.pdf", "1-2", "--output-dir", str(output_dir)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""


def test_extract_pages_refuses_overwrite_overlap_symlink_and_atomic_failure(corpus_dir, database_path, monkeypatch, capsys):
    source_pdf = build_pdf(corpus_dir / "source.pdf", [["Page 1"], ["Page 2"]])
    _insert_pdf_source(database_path, "source.pdf", source_pdf, 2)

    overlap_dir = corpus_dir
    exit_code = cli.main(["extract-pages", "--root", str(corpus_dir), "--database", str(database_path), "source.pdf", "--output-dir", str(overlap_dir)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""

    nested_output = corpus_dir / "exports"
    nested_output.mkdir()
    exit_code = cli.main(["extract-pages", "--root", str(corpus_dir), "--database", str(database_path), "source.pdf", "--output-dir", str(nested_output)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""

    real_output = database_path.parent / "exports"
    real_output.mkdir()
    symlink_output = database_path.parent / "exports-link"
    symlink_output.symlink_to(real_output)
    exit_code = cli.main(["extract-pages", "--root", str(corpus_dir), "--database", str(database_path), "source.pdf", "--output-dir", str(symlink_output)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""

    exit_code = cli.main(["extract-pages", "--root", str(corpus_dir), "--database", str(database_path), "source.pdf", "--output-dir", str(real_output)])
    captured = capsys.readouterr()
    assert exit_code == 0
    summary = _extract_summary(captured.out)
    assert Path(summary["pdf_path"]).is_file()
    assert Path(summary["manifest_path"]).is_file()

    # overwrite refusal on repeat run
    exit_code = cli.main(["extract-pages", "--root", str(corpus_dir), "--database", str(database_path), "source.pdf", "--output-dir", str(real_output)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""

    from tracecite.evidence import page_extraction

    monkeypatch.setattr(page_extraction, "promote_staged_outputs", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    fresh_output = database_path.parent / "exports-2"
    fresh_output.mkdir()
    exit_code = cli.main(["extract-pages", "--root", str(corpus_dir), "--database", str(database_path), "source.pdf", "--output-dir", str(fresh_output)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert not list(fresh_output.iterdir())


def test_extract_pages_rejects_source_changed_since_indexing(corpus_dir, database_path, capsys):
    source_pdf = build_pdf(corpus_dir / "source.pdf", [["Indexed page"]])
    _insert_pdf_source(database_path, "source.pdf", source_pdf, 1)
    build_pdf(source_pdf, [["Changed page"]])
    output_dir = database_path.parent / "exports"
    output_dir.mkdir()

    exit_code = cli.main([
        "extract-pages",
        "--root",
        str(corpus_dir),
        "--database",
        str(database_path),
        "source.pdf",
        "--output-dir",
        str(output_dir),
    ])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert "changed since indexing" in captured.err
    assert not list(output_dir.iterdir())


def test_extract_pages_preserves_racing_existing_output(corpus_dir, database_path, monkeypatch, capsys):
    source_pdf = build_pdf(corpus_dir / "source.pdf", [["Page 1"]])
    _insert_pdf_source(database_path, "source.pdf", source_pdf, 1)
    output_dir = database_path.parent / "exports"
    output_dir.mkdir()

    from tracecite.evidence import page_extraction

    original_promote = page_extraction.promote_staged_outputs

    def race_with_manifest(staged_pdf, staged_manifest, final_pdf, final_manifest):
        final_manifest.write_text("external\n", encoding="utf-8")
        return original_promote(staged_pdf, staged_manifest, final_pdf, final_manifest)

    monkeypatch.setattr(page_extraction, "promote_staged_outputs", race_with_manifest)
    exit_code = cli.main([
        "extract-pages",
        "--root",
        str(corpus_dir),
        "--database",
        str(database_path),
        "source.pdf",
        "--output-dir",
        str(output_dir),
    ])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    remaining = list(output_dir.iterdir())
    assert len(remaining) == 1
    assert remaining[0].suffix == ".json"
    assert remaining[0].read_text(encoding="utf-8") == "external\n"
