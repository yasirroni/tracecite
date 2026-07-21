from __future__ import annotations

from pathlib import Path

from tracecite.evidence import cli, sync as sync_module
from conftest import FakeEmbedder, build_pdf, write_manifest


def test_explicit_config_supplies_runtime_and_inline_rules_for_commands(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    build_pdf(root / "doc.pdf", [["Title", "Profile invocation finds this searchable sentence."]])
    database = root / "tracecite.sqlite"
    config = root / "tracecite.toml"
    config.write_text(
        f'schema_version = 1\nroot = "."\ndatabase = "{database.name}"\nmodel_cache_dir = "model-cache"\n[[source]]\npath = "doc.pdf"\norigin = "local"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(root / ".")
    monkeypatch.setattr(sync_module, "EmbeddingModel", lambda *a, **k: FakeEmbedder())
    assert cli.main(["sync", "--config", str(config)]) == 0
    assert cli.main(["doctor", "--config", str(config)]) == 0
    assert cli.main(["page", "--config", str(config), "doc.pdf", "1"]) == 0
    assert cli.main(["search", "--config", str(config), "searchable", "--limit", "1"]) == 0
    assert cli.main(["verify", "quote", "--config", str(config), "doc.pdf", "1", "Profile invocation finds this searchable sentence."]) == 0
    report = root / "report.md"
    report.write_text(
        'A profile-only report citation works ([Doc, p. 1][doc-p1]).\n\n'
        '> "Profile invocation finds this searchable sentence."\n\n'
        '[doc-p1]: doc.pdf#page=1\n',
        encoding="utf-8",
    )
    assert cli.main(["verify", "report", "--config", str(config), str(report)]) == 0
    assert cli.main(["prune", "--config", str(config)]) == 0


def test_explicit_cli_overrides_profile_and_repeated_manifests_are_layered(tmp_path: Path, monkeypatch):
    profile_root = tmp_path / "profile-root"
    override_root = tmp_path / "override-root"
    profile_root.mkdir()
    override_root.mkdir()
    build_pdf(override_root / "keep.pdf", [["Keep", "Explicit override root content."]])
    tracked = tmp_path / "tracked.toml"
    local = tmp_path / "local.toml"
    tracked.write_text('schema_version = 1\n[[include]]\nglob = "*.pdf"\n', encoding="utf-8")
    local.write_text('schema_version = 1\n[[exclude]]\nglob = "excluded.pdf"\n', encoding="utf-8")
    profile_db = profile_root / "profile.sqlite"
    override_db = tmp_path / "override.sqlite"
    config = tmp_path / "tracecite.toml"
    config.write_text(
        f'schema_version = 1\nroot = "{profile_root.as_posix()}"\ndatabase = "{profile_db.as_posix()}"\nmodel_cache_dir = "profile-cache"\n[[source]]\npath = "ignored.pdf"\norigin = "default"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(sync_module, "EmbeddingModel", lambda *a, **k: FakeEmbedder())

    exit_code = cli.main([
        "sync", "--config", str(config), "--root", str(override_root), "--database", str(override_db),
        "--model-cache-dir", str(tmp_path / "override-cache"), "--manifest", str(tracked), "--manifest", str(local)
    ])

    assert exit_code == 0
    assert override_db.exists()
    assert not profile_db.exists()


def test_config_inline_rules_manifest_union_duplicates_and_all_scalar_overrides(tmp_path: Path, monkeypatch):
    config_root = tmp_path / "config-root"
    override_root = tmp_path / "override-root"
    config_root.mkdir()
    override_root.mkdir()
    config = tmp_path / "tracecite.toml"
    config.write_text(
        f'schema_version = 1\nroot = "{config_root.as_posix()}"\ndatabase = "{(tmp_path / "config.sqlite").as_posix()}"\nmodel_cache_dir = "config-cache"\n'
        '[[include]]\nglob = "*.pdf"\norigin = "default"\n'
        '[[exclude]]\nglob = "skip.pdf"\norigin = "default"\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.toml"
    manifest.write_text('schema_version = 1\n[[include]]\nglob = "*.pdf"\n[[source]]\npath = "extra.md"\n', encoding="utf-8")
    calls = []

    class Report:
        status = "ok"
        sources_added = []
        sources_reparsed = []
        sources_rechunked = []
        sources_renamed = []
        selected_missing_paths = []
        unmatched_globs = []
        indexed_unselected_paths = []
        cleanup_warnings = []
        sources_unchanged = []
        chunks_added = 0
        chunks_updated = 0
        chunks_deleted = 0
        embeddings_generated = 0

    def fake_sync(root, manifests, database, *, model_cache_dir, **kwargs):
        calls.append((Path(root), tuple(manifests), Path(database), Path(model_cache_dir)))
        return Report()

    monkeypatch.setattr(sync_module, "sync", fake_sync)
    override_db = tmp_path / "override.sqlite"
    override_cache = tmp_path / "override-cache"
    assert cli.main([
        "sync", "--config", str(config), "--manifest", str(manifest), "--root", str(override_root),
        "--database", str(override_db), "--model-cache-dir", str(override_cache),
    ]) == 0
    root, manifests, database, model_cache_dir = calls[0]
    assert root == override_root
    assert database == override_db
    assert model_cache_dir == override_cache
    assert manifests == (config, manifest)
    rules = sync_module.load_manifest_rules(manifests)
    assert rules.include_globs == ("*.pdf",)
    assert rules.explicit_paths == ("extra.md",)
    assert not rules.selects_path("skip.pdf")
