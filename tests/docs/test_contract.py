from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from tracecite.docs import (
    BuildSelection,
    BuildVariant,
    DocsBuildResult,
    Language,
    build_docs,
    changed_retained_markdown,
    classify_render_inputs,
    discover_render_inputs,
    select_build_variant,
    snapshot_retained_markdown,
    stage_retained_markdown,
)
from tracecite.docs.contract import DocsEvidenceContract


def test_existing_docs_public_api_remains_importable() -> None:
    assert Language is not None
    assert BuildVariant is not None
    assert BuildSelection is not None
    assert DocsBuildResult is not None
    assert all(callable(name) for name in (
        discover_render_inputs,
        classify_render_inputs,
        select_build_variant,
        snapshot_retained_markdown,
        changed_retained_markdown,
        stage_retained_markdown,
        build_docs,
    ))


def test_contract_has_exact_schema_fields(tmp_path: Path) -> None:
    assert [field.name for field in fields(DocsEvidenceContract)] == [
        "authored_root",
        "retained_root",
        "staged_root",
        "source_links",
        "index_output",
        "publication_exclude",
        "host_render_command",
    ]


def test_contract_rejects_unknown_host_fields(tmp_path: Path) -> None:
    config = tmp_path / "docs.toml"
    config.write_text(
        'schema_version = 1\n[docs]\nauthored_root = "docs/src"\n'
        'retained_root = "docs/src/generated"\n'
        'staged_root = "docs/.tracecite-stage"\n'
        'source_links = "docs/source-links.toml"\n'
        'index_output = ".tracecite/docs/tracecite.sqlite"\n'
        'publication_exclude = []\ntracks = ["bad"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown"):
        from tracecite.docs.config import load_docs_contract
        load_docs_contract(config, repo_root=tmp_path)
