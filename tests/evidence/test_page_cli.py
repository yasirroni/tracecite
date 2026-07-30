from __future__ import annotations

from pathlib import Path

from tracecite import cli
from tracecite.evidence import schema


def _insert_source_with_pages(database_path: Path, source_path: str, page_texts: dict[int, str]) -> None:
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
            ) VALUES (?, 'pdf', NULL, NULL, NULL, 'sha', 1, 1, 'parser', '1', '{}', 'chunker', '1', '{}', '1', '{}', 'now', 'ok')
            """,
            (source_path,),
        )
        source_pk = conn.execute("SELECT source_pk FROM sources WHERE path = ?", (source_path,)).fetchone()["source_pk"]
        for physical_page, text in page_texts.items():
            conn.execute(
                """
                INSERT INTO pages (
                    source_pk, physical_page, printed_label, text,
                    extraction_method, extraction_status, section_candidates, layout_json
                ) VALUES (?, ?, NULL, ?, 'pdf', 'ok', NULL, NULL)
                """,
                (source_pk, physical_page, text),
            )
        conn.commit()
    finally:
        conn.close()


def test_cli_page_defaults_to_page_one_and_preserves_single_page_output(tmp_path, capsys):
    root = tmp_path / "sources"
    root.mkdir()
    database_path = tmp_path / "runtime" / "tracecite.sqlite"
    _insert_source_with_pages(database_path, "doc.pdf", {1: "Page one text", 2: "Page two text"})

    exit_code = cli.main(["page", "--root", str(root), "--database", str(database_path), "doc.pdf"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == "Page one text\n"
    assert captured.err == ""


def test_cli_page_preserves_explicit_single_page_output_byte_for_byte(tmp_path, capsys):
    root = tmp_path / "sources"
    root.mkdir()
    database_path = tmp_path / "runtime" / "tracecite.sqlite"
    _insert_source_with_pages(database_path, "doc.pdf", {1: "Page one text", 2: "Page two text"})

    exit_code = cli.main(["page", "--root", str(root), "--database", str(database_path), "doc.pdf", "2"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == "Page two text\n"
    assert captured.err == ""


def test_cli_page_supports_open_closed_list_and_all_selections_with_delimiters(tmp_path, capsys):
    root = tmp_path / "sources"
    root.mkdir()
    database_path = tmp_path / "runtime" / "tracecite.sqlite"
    _insert_source_with_pages(
        database_path,
        "doc.pdf",
        {1: "Page 1 text", 2: "Page 2 text", 3: "Page 3 text", 4: "Page 4 text", 5: "Page 5 text"},
    )

    cases = [
        ("2-4", "--- physical page 2 ---\nPage 2 text\n\n--- physical page 3 ---\nPage 3 text\n\n--- physical page 4 ---\nPage 4 text\n"),
        ("3-", "--- physical page 3 ---\nPage 3 text\n\n--- physical page 4 ---\nPage 4 text\n\n--- physical page 5 ---\nPage 5 text\n"),
        ("-3", "--- physical page 1 ---\nPage 1 text\n\n--- physical page 2 ---\nPage 2 text\n\n--- physical page 3 ---\nPage 3 text\n"),
        ("5,2-3,1", "--- physical page 1 ---\nPage 1 text\n\n--- physical page 2 ---\nPage 2 text\n\n--- physical page 3 ---\nPage 3 text\n\n--- physical page 5 ---\nPage 5 text\n"),
        ("all", "--- physical page 1 ---\nPage 1 text\n\n--- physical page 2 ---\nPage 2 text\n\n--- physical page 3 ---\nPage 3 text\n\n--- physical page 4 ---\nPage 4 text\n\n--- physical page 5 ---\nPage 5 text\n"),
    ]

    for selector, expected in cases:
        exit_code = cli.main(["page", "--root", str(root), "--database", str(database_path), "doc.pdf", selector])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert captured.out == expected
        assert captured.err == ""


def test_cli_page_rejects_missing_pages_before_emitting_stdout(tmp_path, capsys):
    root = tmp_path / "sources"
    root.mkdir()
    database_path = tmp_path / "runtime" / "tracecite.sqlite"
    _insert_source_with_pages(database_path, "doc.pdf", {1: "Page 1 text", 3: "Page 3 text"})

    exit_code = cli.main(["page", "--root", str(root), "--database", str(database_path), "doc.pdf", "1-3"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "page 2" in captured.err


def test_cli_page_rejects_path_escapes_and_missing_database(tmp_path, capsys):
    root = tmp_path / "sources"
    root.mkdir()
    database_path = tmp_path / "runtime" / "tracecite.sqlite"
    _insert_source_with_pages(database_path, "doc.pdf", {1: "Page 1 text"})

    exit_code = cli.main(["page", "--root", str(root), "--database", str(database_path), "../doc.pdf"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "path-error" in captured.err

    missing_db = tmp_path / "missing.sqlite"
    exit_code = cli.main(["page", "--root", str(root), "--database", str(missing_db), "doc.pdf"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "database does not exist" in captured.err


def test_cli_page_reports_non_paginated_sources_without_crashing(tmp_path, capsys):
    root = tmp_path / "sources"
    root.mkdir()
    database_path = tmp_path / "runtime" / "tracecite.sqlite"
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
            ) VALUES ('note.md', 'markdown', NULL, NULL, NULL, 'sha', 1, 1,
                      'parser', '1', '{}', 'chunker', '1', '{}', '1', '{}', 'now', 'ok')
            """
        )
        conn.commit()
    finally:
        conn.close()

    exit_code = cli.main(["page", "--root", str(root), "--database", str(database_path), "note.md"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "page 1" in captured.err
