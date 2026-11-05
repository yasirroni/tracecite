from __future__ import annotations

import json

from conftest import (
    build_markdown,
    build_pdf,
    sync_with_fake_model,
    write_manifest,
)

from tracecite import cli


def test_search_results_carry_page_asset_fields_for_pdfs_only(
    corpus_dir, manifest_path, database_path, monkeypatch, capsys
):
    build_pdf(corpus_dir / "figure.pdf", [["Figure report text"], ["Second page"]])
    build_markdown(
        corpus_dir / "note.md",
        "# Heading\n\nThis note mentions hydrogen storage and grids.\n",
    )
    write_manifest(manifest_path, {"figure.pdf": "figure.pdf", "note.md": "note.md"})
    sync_with_fake_model(monkeypatch, corpus_dir, manifest_path, database_path)
    capsys.readouterr()

    assert cli.main(["search", "--database", str(database_path), "report"]) == 0
    payload = json.loads(capsys.readouterr().out)
    pdf = next(result for result in payload if result["source_path"] == "figure.pdf")
    assert pdf["page_render"]["asset_type"] == "page-render"
    assert isinstance(pdf["figure_crops"], list)
    assert "pdf_link" in pdf and "heading_path" in pdf

    assert (
        cli.main(["search", "--database", str(database_path), "hydrogen storage"]) == 0
    )
    payload = json.loads(capsys.readouterr().out)
    note = next(result for result in payload if result["source_path"] == "note.md")
    assert note["page_render"] is None
    assert note["figure_crops"] == []
