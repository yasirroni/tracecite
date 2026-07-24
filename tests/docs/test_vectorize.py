from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tracecite import cli
from tracecite.docs import (
    doctor_docs_index,
    load_docs_contract,
    prepare_docs_index_input,
    search_docs_index,
    sync_docs_index,
)
from tracecite.docs import vectorize
from tracecite.docs.vectorize import docs_index_freshness_diagnostics
from tracecite.evidence import schema

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "docs-vector"


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        vectors: list[list[float]] = []
        for text in texts:
            seed = sum((index + 1) * ord(char) for index, char in enumerate(text))
            vector = [0.0] * schema.EMBEDDING_DIMENSIONS
            vector[seed % schema.EMBEDDING_DIMENSIONS] = 1.0
            vector[(seed // 7) % schema.EMBEDDING_DIMENSIONS] = 0.5
            vectors.append(vector)
        return vectors


@pytest.fixture
def make_embedder():
    def _make() -> FakeEmbedder:
        return FakeEmbedder()

    return _make


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "docs/authored").mkdir(parents=True)
    retained = tmp_path / "docs/retained"
    retained.mkdir()
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources/report.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "docs/source-links.toml").write_text(
        """schema_version = 2

[[source]]
title = "Report"
publisher = "Publisher"
local_path = "sources/report.pdf"
public_url = "https://publisher.example/report.pdf"
public_origin = "official"
""",
        encoding="utf-8",
    )
    (retained / "index.md").write_text(
        "# Topic\n\nFixture query text about coal plant retirement planning.\n\n"
        "See [report](../../sources/report.pdf#page=1).\n",
        encoding="utf-8",
    )
    config = tmp_path / "docs/tracecite.toml"
    config.write_text(
        """schema_version = 1
[docs]
authored_root = "docs/authored"
retained_root = "docs/retained"
staged_root = "docs/.tracecite-stage"
source_links = "docs/source-links.toml"
index_output = ".tracecite/docs.sqlite"
publication_exclude = []
""",
        encoding="utf-8",
    )
    return config, tmp_path


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _touch_future_mtime(path: Path) -> None:
    stat = path.stat()
    os.utime(path, (stat.st_mtime + 5, stat.st_mtime + 5))


def _index_snapshot(database_path: Path) -> dict[str, object]:
    conn = schema.connect(database_path)
    try:
        sources = [row["path"] for row in conn.execute("SELECT path FROM sources ORDER BY path")]
        chunks = conn.execute(
            "SELECT chunk_id, source_pk, logical_key, lexical_hash, semantic_input_hash "
            "FROM chunks ORDER BY chunk_id"
        ).fetchall()
        return {
            "sources": sources,
            "chunks": [
                {
                    "logical_key": row["logical_key"],
                    "lexical_hash": row["lexical_hash"],
                    "semantic_input_hash": row["semantic_input_hash"],
                }
                for row in chunks
            ],
        }
    finally:
        conn.close()


def test_mirror_preserves_relative_paths_and_augments_tables(tmp_path: Path) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    before = _snapshot(contract.retained_root)
    profile = prepare_docs_index_input(contract, repo_root=root)
    assert before == _snapshot(contract.retained_root)
    mirror = profile.input_root / "index.md"
    assert mirror.is_file()
    text = mirror.read_text(encoding="utf-8")
    assert "Fixture query text" in text
    assert profile.manifest_path.is_file()
    assert 'glob = "**/*.md"' in profile.manifest_path.read_text(encoding="utf-8")


def test_prepare_atomically_replaces_index_input_and_preserves_siblings(tmp_path: Path) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    profile = prepare_docs_index_input(contract, repo_root=root)
    sentinel = contract.staged_root / "local"
    sentinel.mkdir(parents=True)
    (sentinel / "keep.md").write_text("keep", encoding="utf-8")
    first = (profile.input_root / "index.md").read_text(encoding="utf-8")
    prepare_docs_index_input(contract, repo_root=root)
    assert (profile.input_root / "index.md").read_text(encoding="utf-8") == first
    assert (sentinel / "keep.md").read_text(encoding="utf-8") == "keep"


def test_prepare_failure_preserves_previous_index_input(tmp_path: Path) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    prepare_docs_index_input(contract, repo_root=root)
    previous = (contract.staged_root / "index-input/index.md").read_text(encoding="utf-8")
    (contract.retained_root / "index.md").write_text(
        "See [bad](../../sources/missing.pdf#page=0).\n", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        prepare_docs_index_input(contract, repo_root=root)
    assert (contract.staged_root / "index-input/index.md").read_text(encoding="utf-8") == previous


def test_prepare_rolls_back_both_files_when_manifest_promotion_fails(
    tmp_path: Path, monkeypatch
) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    prepare_docs_index_input(contract, repo_root=root)
    previous_mirror = (contract.staged_root / "index-input/index.md").read_text(encoding="utf-8")
    previous_manifest = (contract.staged_root / "index-input.manifest.toml").read_text(encoding="utf-8")

    real_replace = os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] == 4:
            raise OSError("simulated failure promoting manifest")
        return real_replace(src, dst)

    monkeypatch.setattr(vectorize.os, "replace", flaky_replace)
    with pytest.raises(OSError):
        prepare_docs_index_input(contract, repo_root=root)

    assert (contract.staged_root / "index-input/index.md").read_text(encoding="utf-8") == previous_mirror
    assert (
        contract.staged_root / "index-input.manifest.toml"
    ).read_text(encoding="utf-8") == previous_manifest
    assert list(contract.staged_root.glob(".*.previous")) == []


def test_doctor_reports_stale_manifest_content(tmp_path: Path, make_embedder) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    sync_docs_index(contract, repo_root=root, embedder=make_embedder())
    assert doctor_docs_index(contract, repo_root=root) == ()
    (contract.staged_root / "index-input.manifest.toml").write_text(
        "this does not match the current docs contract\n", encoding="utf-8"
    )
    issues = doctor_docs_index(contract, repo_root=root)
    assert any("manifest" in issue and "stale" in issue for issue in issues)


def test_doctor_reports_database_stale_relative_to_rebuilt_mirror(
    tmp_path: Path, make_embedder
) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    sync_docs_index(contract, repo_root=root, embedder=make_embedder())
    assert doctor_docs_index(contract, repo_root=root) == ()
    (contract.retained_root / "index.md").write_text(
        "# Topic\n\nUpdated fixture query text about coal plant retirement planning.\n\n"
        "See [report](../../sources/report.pdf#page=1).\n",
        encoding="utf-8",
    )
    prepare_docs_index_input(contract, repo_root=root)
    issues = doctor_docs_index(contract, repo_root=root)
    assert any("stale relative to mirror" in issue for issue in issues)


def test_publication_exclude_is_translated_into_manifest(tmp_path: Path) -> None:
    config, root = _fixture(tmp_path)
    excluded = root / "docs/retained/private"
    excluded.mkdir()
    (excluded / "secret.md").write_text("# secret\n", encoding="utf-8")
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "publication_exclude = []",
            'publication_exclude = ["docs/retained/private"]',
        ),
        encoding="utf-8",
    )
    contract = load_docs_contract(config, repo_root=root)
    profile = prepare_docs_index_input(contract, repo_root=root)
    manifest = profile.manifest_path.read_text(encoding="utf-8")
    assert 'glob = "private/**"' in manifest
    assert not (profile.input_root / "private/secret.md").exists()


def test_malformed_source_link_blocks_prepare_before_database(tmp_path: Path, make_embedder) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    (contract.retained_root / "index.md").write_text(
        "See [bad](../../sources/report.pdf#page=0).\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="index.md"):
        prepare_docs_index_input(contract, repo_root=root)
    assert not contract.index_output.exists()


def test_sync_indexes_and_repeated_sync_is_unchanged(tmp_path: Path, make_embedder) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    embedder = make_embedder()
    first = sync_docs_index(contract, repo_root=root, embedder=embedder)
    assert first.sync_report.sources_added == ["index.md"]
    calls_before = len(embedder.calls)
    second = sync_docs_index(contract, repo_root=root, embedder=embedder)
    assert second.sync_report.sources_unchanged == ["index.md"]
    assert not second.sync_report.wrote_anything
    assert len(embedder.calls) == calls_before


def test_mtime_only_touch_does_not_change_semantic_identity(tmp_path: Path, make_embedder) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    embedder = make_embedder()
    sync_docs_index(contract, repo_root=root, embedder=embedder)
    before = _index_snapshot(contract.index_output)
    mirror_file = contract.staged_root / "index-input/index.md"
    _touch_future_mtime(mirror_file)
    report = sync_docs_index(contract, repo_root=root, embedder=embedder)
    assert report.sync_report.sources_unchanged == ["index.md"]
    assert _index_snapshot(contract.index_output) == before


def test_content_change_and_rename_follow_existing_sync_semantics(tmp_path: Path, make_embedder) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    embedder = make_embedder()
    sync_docs_index(contract, repo_root=root, embedder=embedder)
    retained = contract.retained_root / "index.md"
    retained.write_text(
        "# Renamed topic\n\nUpdated fixture query text about coal plant retirement planning.\n",
        encoding="utf-8",
    )
    renamed = contract.retained_root / "renamed.md"
    retained.rename(renamed)
    report = sync_docs_index(contract, repo_root=root, embedder=embedder)
    assert "renamed.md" in report.sync_report.sources_added or report.sync_report.sources_renamed


def test_same_database_chunk_uuids_remain_stable_on_repeat_sync(tmp_path: Path, make_embedder) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    embedder = make_embedder()
    sync_docs_index(contract, repo_root=root, embedder=embedder)
    conn = schema.connect(contract.index_output)
    try:
        first_ids = [row["chunk_id"] for row in conn.execute("SELECT chunk_id FROM chunks ORDER BY chunk_id")]
    finally:
        conn.close()
    sync_docs_index(contract, repo_root=root, embedder=embedder)
    conn = schema.connect(contract.index_output)
    try:
        second_ids = [row["chunk_id"] for row in conn.execute("SELECT chunk_id FROM chunks ORDER BY chunk_id")]
    finally:
        conn.close()
    assert first_ids == second_ids


def test_two_fresh_indexes_are_deterministic_for_paths_keys_hashes_and_search(
    tmp_path: Path, make_embedder
) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    embedder = make_embedder()

    def build_fresh() -> tuple[dict[str, object], list[dict]]:
        fresh_root = tmp_path / f"fresh-{len(list(tmp_path.glob('fresh-*')))}"
        fresh_root.mkdir()
        for relative in ("docs", "sources"):
            shutil.copytree(root / relative, fresh_root / relative)
        fresh_config = fresh_root / "docs/tracecite.toml"
        fresh_config.write_text(
            config.read_text(encoding="utf-8").replace(
                ".tracecite/docs.sqlite",
                ".tracecite/fresh.sqlite",
            ),
            encoding="utf-8",
        )
        fresh_contract = load_docs_contract(fresh_config, repo_root=fresh_root)
        sync_docs_index(fresh_contract, repo_root=fresh_root, embedder=make_embedder())
        results = search_docs_index(
            fresh_contract,
            "fixture query coal plant retirement",
            repo_root=fresh_root,
            embedder=make_embedder(),
        )
        return _index_snapshot(fresh_contract.index_output), results

    first_snapshot, first_results = build_fresh()
    second_snapshot, second_results = build_fresh()
    assert first_snapshot == second_snapshot
    assert first_results == second_results


def test_index_input_freshness_reports_leaked_artifacts(tmp_path: Path) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    prepare_docs_index_input(contract, repo_root=root)
    leaked = contract.staged_root / "index-input/leaked.html"
    leaked.write_text("<html></html>", encoding="utf-8")
    diagnostics = docs_index_freshness_diagnostics(contract, repo_root=root)
    assert any("index-input leaked artifact: leaked.html" in issue for issue in diagnostics)


def test_docs_index_freshness_reports_missing_index_when_never_indexed(tmp_path: Path) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    diagnostics = docs_index_freshness_diagnostics(contract, repo_root=root)
    assert any("index-input mirror is missing" in issue for issue in diagnostics)
    assert any("documentation index database is missing" in issue for issue in diagnostics)


def test_search_and_doctor_report_missing_or_stale_index_input(tmp_path: Path, make_embedder) -> None:
    config, root = _fixture(tmp_path)
    contract = load_docs_contract(config, repo_root=root)
    issues = doctor_docs_index(contract, repo_root=root)
    assert any("missing" in issue for issue in issues)
    sync_docs_index(contract, repo_root=root, embedder=make_embedder())
    assert doctor_docs_index(contract, repo_root=root) == ()
    results = search_docs_index(contract, "fixture query", repo_root=root, embedder=make_embedder())
    assert results
    assert "chunk_id" not in results[0]
    empty = search_docs_index(contract, "", repo_root=root, embedder=make_embedder())
    assert empty == [] or isinstance(empty, list)


def test_docs_index_cli_help_and_fixture_commands(tmp_path: Path, make_embedder) -> None:
    for command in ("index", "search", "doctor"):
        result = subprocess.run(
            [sys.executable, "-m", "tracecite", "docs", command, "--help"],
            text=True,
            capture_output=True,
            check=True,
        )
        assert "--docs-config" in result.stdout
        assert "--repo-root" in result.stdout

    fixture_root = tmp_path / "fixture"
    shutil.copytree(FIXTURE_ROOT, fixture_root)
    contract = load_docs_contract(fixture_root / "tracecite.toml", repo_root=fixture_root)
    embedder = make_embedder()
    index_result = sync_docs_index(contract, repo_root=fixture_root, embedder=embedder)
    assert index_result.sync_report.status == "ok"

    index_args = cli.build_parser().parse_args(
        [
            "docs",
            "index",
            "--docs-config",
            str(fixture_root / "tracecite.toml"),
            "--repo-root",
            str(fixture_root),
        ]
    )
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(cli, "sync_docs_index", lambda *_args, **_kwargs: index_result)
        assert cli._docs_index(index_args) == 0

    search_args = cli.build_parser().parse_args(
        [
            "docs",
            "search",
            "fixture query",
            "--docs-config",
            str(fixture_root / "tracecite.toml"),
            "--repo-root",
            str(fixture_root),
        ]
    )
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(
            cli,
            "search_docs_index",
            lambda *_args, **_kwargs: search_docs_index(
                contract, "fixture query", repo_root=fixture_root, embedder=embedder
            ),
        )
        assert cli._docs_search(search_args) == 0

    doctor_args = cli.build_parser().parse_args(
        [
            "docs",
            "doctor",
            "--docs-config",
            str(fixture_root / "tracecite.toml"),
            "--repo-root",
            str(fixture_root),
        ]
    )
    assert cli._docs_doctor(doctor_args) == 0


def test_docs_index_commands_require_evidence_extra_guidance_when_missing() -> None:
    args = cli.build_parser().parse_args(
        ["docs", "index", "--docs-config", "docs/tracecite.toml", "--repo-root", "."]
    )

    def _raise(*_args, **_kwargs):
        raise ModuleNotFoundError("tracecite[evidence] is required")

    with patch.object(cli, "load_docs_contract", return_value=object()), patch.object(
        cli, "sync_docs_index", side_effect=_raise
    ):
        assert cli._docs_index(args) == 2


def test_docs_index_search_doctor_parser_options_are_explicit() -> None:
    index = cli.build_parser().parse_args(
        ["docs", "index", "--docs-config", "docs/tracecite.toml", "--repo-root", "."]
    )
    assert index.docs_command == "index"
    search = cli.build_parser().parse_args(
        [
            "docs",
            "search",
            "fixture query",
            "--docs-config",
            "docs/tracecite.toml",
            "--repo-root",
            ".",
            "--limit",
            "3",
        ]
    )
    assert search.query == "fixture query"
    assert search.limit == 3
