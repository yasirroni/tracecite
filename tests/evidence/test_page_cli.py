from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest
from conftest import insert_source

from tracecite import cli
from tracecite.evidence import schema


def _insert_source_with_pages(
    database_path: Path, source_path: str, page_texts: dict[int, str]
) -> None:
    with closing(schema.connect(database_path)) as conn:
        schema.ensure_schema(conn)
        source_pk = insert_source(conn, source_path)
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


def _delimited(*pages: int) -> str:
    return "\n".join(
        f"--- physical page {page} ---\nPage {page} text\n" for page in pages
    )


# Selection grammar is owned by test_page_selection.py; these cases pin the
# CLI output shape: one page prints bare text, several print delimited blocks
# in page order.
@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ([], "Page 1 text\n"),
        (["2"], "Page 2 text\n"),
        (["5,2-3,1"], _delimited(1, 2, 3, 5)),
        (["all"], _delimited(1, 2, 3, 4, 5)),
    ],
    ids=["default", "single", "list", "all"],
)
def test_cli_page_output_for_page_selections(selector, expected, tmp_path, capsys):
    root = tmp_path / "sources"
    root.mkdir()
    database_path = tmp_path / "runtime" / "tracecite.sqlite"
    _insert_source_with_pages(
        database_path, "doc.pdf", {page: f"Page {page} text" for page in range(1, 6)}
    )

    exit_code = cli.main(
        [
            "page",
            "--root",
            str(root),
            "--database",
            str(database_path),
            "doc.pdf",
            *selector,
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == expected
    assert captured.err == ""


def test_cli_page_rejects_missing_pages_before_emitting_stdout(tmp_path, capsys):
    root = tmp_path / "sources"
    root.mkdir()
    database_path = tmp_path / "runtime" / "tracecite.sqlite"
    _insert_source_with_pages(
        database_path, "doc.pdf", {1: "Page 1 text", 3: "Page 3 text"}
    )

    exit_code = cli.main(
        [
            "page",
            "--root",
            str(root),
            "--database",
            str(database_path),
            "doc.pdf",
            "1-3",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "doc.pdf" in captured.err


def test_cli_page_reports_non_paginated_sources_without_crashing(tmp_path, capsys):
    root = tmp_path / "sources"
    root.mkdir()
    database_path = tmp_path / "runtime" / "tracecite.sqlite"
    with closing(schema.connect(database_path)) as conn:
        schema.ensure_schema(conn)
        insert_source(conn, "note.md", "markdown")
        conn.commit()

    exit_code = cli.main(
        ["page", "--root", str(root), "--database", str(database_path), "note.md"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "note.md" in captured.err


def test_cli_page_names_the_requested_page_of_an_unindexed_source(tmp_path, capsys):
    database_path = tmp_path / "tracecite.sqlite"
    with closing(schema.connect(database_path)) as conn:
        schema.ensure_schema(conn)
    args = ["page", "--root", str(tmp_path), "--database", str(database_path)]

    assert cli.main([*args, "missing.pdf", "4"]) == 1
    assert capsys.readouterr().err == "not-found: missing.pdf page 4\n"
