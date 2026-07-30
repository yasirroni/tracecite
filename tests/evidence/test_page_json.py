from __future__ import annotations

import json
from pathlib import Path

from tracecite import cli
from tracecite.evidence import schema, sync as sync_module

from conftest import build_pdf_with_image_only_page, write_manifest, FakeEmbedder


def _sync_pdf_with_assets(corpus_dir: Path, manifest_path: Path, database_path: Path, monkeypatch):
    pdf_path = build_pdf_with_image_only_page(corpus_dir / "figure.pdf")
    write_manifest(manifest_path, {"figure.pdf": "figure.pdf"})
    monkeypatch.setattr(sync_module, "EmbeddingModel", lambda *args, **kwargs: FakeEmbedder())
    assert sync_module.sync(corpus_dir, manifest_path, database_path, embedder=FakeEmbedder()).status == "ok"
    return pdf_path


def test_page_json_returns_ordered_array_with_page_assets(corpus_dir, manifest_path, database_path, monkeypatch, capsys):
    _sync_pdf_with_assets(corpus_dir, manifest_path, database_path, monkeypatch)

    exit_code = cli.main([
        "page",
        "--root",
        str(corpus_dir),
        "--database",
        str(database_path),
        "--format",
        "json",
        "figure.pdf",
        "1",
    ])
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


def test_page_json_preserves_order_for_multiple_selected_pages(corpus_dir, manifest_path, database_path, monkeypatch, capsys):
    from conftest import build_pdf

    build_pdf(corpus_dir / "figure.pdf", [["First page"], ["Second page"]])
    write_manifest(manifest_path, {"figure.pdf": "figure.pdf"})
    monkeypatch.setattr(sync_module, "EmbeddingModel", lambda *args, **kwargs: FakeEmbedder())
    assert sync_module.sync(corpus_dir, manifest_path, database_path, embedder=FakeEmbedder()).status == "ok"

    exit_code = cli.main([
        "page",
        "--root",
        str(corpus_dir),
        "--database",
        str(database_path),
        "--format",
        "json",
        "figure.pdf",
        "2,1",
    ])
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert [page["physical_page"] for page in payload] == [1, 2]


def test_page_json_fails_on_missing_or_escaped_assets_before_stdout(corpus_dir, manifest_path, database_path, monkeypatch, capsys):
    _sync_pdf_with_assets(corpus_dir, manifest_path, database_path, monkeypatch)
    conn = schema.connect(database_path)
    try:
        asset_row = conn.execute("SELECT asset_id, asset_path FROM assets LIMIT 1").fetchone()
        asset_path = schema.resolve_asset_path(database_path, asset_row["asset_path"])
        asset_path.unlink()
    finally:
        conn.close()

    exit_code = cli.main([
        "page",
        "--root",
        str(corpus_dir),
        "--database",
        str(database_path),
        "--format",
        "json",
        "figure.pdf",
        "1",
    ])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""


def test_page_json_fails_on_asset_hash_mismatch_before_stdout(corpus_dir, manifest_path, database_path, monkeypatch, capsys):
    _sync_pdf_with_assets(corpus_dir, manifest_path, database_path, monkeypatch)
    conn = schema.connect(database_path)
    try:
        asset_row = conn.execute("SELECT asset_path FROM assets LIMIT 1").fetchone()
        asset_path = schema.resolve_asset_path(database_path, asset_row["asset_path"])
        asset_path.write_bytes(asset_path.read_bytes() + b"tampered")
    finally:
        conn.close()

    exit_code = cli.main([
        "page",
        "--root",
        str(corpus_dir),
        "--database",
        str(database_path),
        "--format",
        "json",
        "figure.pdf",
        "1",
    ])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "hash" in captured.err


def test_page_json_fails_on_escaped_asset_paths_before_stdout(corpus_dir, manifest_path, database_path, monkeypatch, capsys):
    _sync_pdf_with_assets(corpus_dir, manifest_path, database_path, monkeypatch)
    conn = schema.connect(database_path)
    try:
        asset_id = conn.execute("SELECT asset_id FROM assets WHERE asset_type = 'page-render' LIMIT 1").fetchone()["asset_id"]
        conn.execute("UPDATE assets SET asset_path = '/tmp/escape.pdf' WHERE asset_id = ?", (asset_id,))
        conn.commit()
    finally:
        conn.close()

    exit_code = cli.main([
        "page",
        "--root",
        str(corpus_dir),
        "--database",
        str(database_path),
        "--format",
        "json",
        "figure.pdf",
        "1",
    ])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
