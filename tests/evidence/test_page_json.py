from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

import pytest
from conftest import (
    build_pdf,
    build_pdf_with_image_only_page,
    requires_tesseract,
    sync_with_fake_model,
    write_manifest,
)

from tracecite import cli
from tracecite.evidence import schema


def _page_json(root, database_path, *arguments) -> int:
    return cli.main(
        [
            "page",
            "--root",
            str(root),
            "--database",
            str(database_path),
            "--format",
            "json",
            *arguments,
        ]
    )


def _sync_pdf_with_assets(
    corpus_dir: Path, manifest_path: Path, database_path: Path, monkeypatch
):
    pdf_path = build_pdf_with_image_only_page(corpus_dir / "figure.pdf")
    write_manifest(manifest_path, {"figure.pdf": "figure.pdf"})
    sync_with_fake_model(monkeypatch, corpus_dir, manifest_path, database_path)
    return pdf_path


@requires_tesseract
def test_page_json_returns_ordered_array_with_page_assets(
    corpus_dir, manifest_path, database_path, monkeypatch, capsys
):
    _sync_pdf_with_assets(corpus_dir, manifest_path, database_path, monkeypatch)

    exit_code = _page_json(corpus_dir, database_path, "figure.pdf", "1")
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert isinstance(payload, list)
    assert [page["physical_page"] for page in payload] == [1]
    page = payload[0]
    assert page["source_path"] == "figure.pdf"
    assert page["text"]
    assert page["pdf_link"] == "figure.pdf#page=1"
    assert page["page_render"]["asset_type"] == "page-render"
    assert page["page_render"]["resolved_path"]
    assert isinstance(page["figure_crops"], list)


def test_page_json_preserves_order_for_multiple_selected_pages(
    corpus_dir, manifest_path, database_path, monkeypatch, capsys
):
    build_pdf(corpus_dir / "figure.pdf", [["First page"], ["Second page"]])
    write_manifest(manifest_path, {"figure.pdf": "figure.pdf"})
    sync_with_fake_model(monkeypatch, corpus_dir, manifest_path, database_path)

    exit_code = _page_json(corpus_dir, database_path, "figure.pdf", "2, 1")
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert [page["physical_page"] for page in payload] == [1, 2]


def _delete_asset(conn, database_path):
    row = conn.execute("SELECT asset_path FROM assets LIMIT 1").fetchone()
    schema.resolve_asset_path(database_path, row["asset_path"]).unlink()


def _tamper_asset(conn, database_path):
    row = conn.execute("SELECT asset_path FROM assets LIMIT 1").fetchone()
    path = schema.resolve_asset_path(database_path, row["asset_path"])
    path.write_bytes(path.read_bytes() + b"tampered")


def _escape_asset_path(conn, database_path):
    conn.execute(
        "UPDATE assets SET asset_path = '/tmp/escape.pdf'"
        " WHERE asset_type = 'page-render'"
    )
    conn.commit()


@pytest.mark.parametrize(
    ("corrupt", "expected_exit"),
    [(_delete_asset, 1), (_tamper_asset, 1), (_escape_asset_path, 2)],
    ids=["missing", "hash-mismatch", "escaped-path"],
)
def test_page_json_fails_on_bad_assets_before_stdout(
    corrupt,
    expected_exit,
    corpus_dir,
    manifest_path,
    database_path,
    monkeypatch,
    capsys,
):
    _sync_pdf_with_assets(corpus_dir, manifest_path, database_path, monkeypatch)
    with closing(schema.connect(database_path)) as conn:
        corrupt(conn, database_path)

    exit_code = _page_json(corpus_dir, database_path, "figure.pdf", "1")
    captured = capsys.readouterr()
    assert exit_code == expected_exit
    assert captured.out == ""
