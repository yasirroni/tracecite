from __future__ import annotations

import json

from tracecite import cli
from tracecite.evidence import sync as sync_module

from conftest import build_markdown, build_pdf, write_manifest, FakeEmbedder


def test_search_pdf_results_expose_page_assets_without_losing_existing_fields(corpus_dir, manifest_path, database_path, monkeypatch, capsys):
    build_pdf(corpus_dir / "figure.pdf", [["Figure report text"], ["Second page"]])
    write_manifest(manifest_path, {"figure.pdf": "figure.pdf"})
    monkeypatch.setattr(sync_module, "EmbeddingModel", lambda *args, **kwargs: FakeEmbedder())
    assert sync_module.sync(corpus_dir, manifest_path, database_path, embedder=FakeEmbedder()).status == "ok"
    capsys.readouterr()

    exit_code = cli.main(["search", "--database", str(database_path), "report"])
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload
    result = payload[0]
    assert result["source_path"] == "figure.pdf"
    assert "page_render" in result
    assert "figure_crops" in result
    assert result["page_render"]["asset_type"] == "page-render"
    assert isinstance(result["figure_crops"], list)
    assert "pdf_link" in result
    assert "heading_path" in result


def test_search_markdown_results_keep_page_asset_fields_null_or_empty(corpus_dir, manifest_path, database_path, monkeypatch, capsys):
    build_markdown(corpus_dir / "note.md", "# Heading\n\nThis note mentions hydrogen storage and grids.\n")
    write_manifest(manifest_path, {"note.md": "note.md"})
    monkeypatch.setattr(sync_module, "EmbeddingModel", lambda *args, **kwargs: FakeEmbedder())
    assert sync_module.sync(corpus_dir, manifest_path, database_path, embedder=FakeEmbedder()).status == "ok"
    capsys.readouterr()

    exit_code = cli.main(["search", "--database", str(database_path), "hydrogen storage"])
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload
    result = payload[0]
    assert result["source_path"] == "note.md"
    assert result["page_render"] is None
    assert result["figure_crops"] == []
