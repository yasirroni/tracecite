from __future__ import annotations

from pathlib import Path

import pytest


def test_manifest_explicit_include_exclude_and_missing(tmp_path: Path):
    from tracecite.evidence.manifest import merge_manifests, resolve_sources

    root = tmp_path / "root"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "keep.md").write_text("keep", encoding="utf-8")
    (root / "docs" / "skip.md").write_text("skip", encoding="utf-8")
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(
        """
schema_version = 1
[[source]]
path = "missing.md"
[[include]]
glob = "docs/**/*.md"
[[exclude]]
glob = "docs/skip.md"
""".strip(),
        encoding="utf-8",
    )
    rules = merge_manifests([manifest])
    selection = resolve_sources(root, rules, indexed_paths=["docs/old.md"])
    assert selection.available_paths == ("docs/keep.md",)
    assert selection.missing_explicit_paths == ("missing.md",)
    assert selection.excluded_paths == ("docs/skip.md",)
    assert rules.selects_path("docs/old.md")
    assert "docs/old.md" in selection.selected_existing_paths


def test_manifest_rejects_escape_and_unsupported_extension(tmp_path: Path):
    from tracecite.evidence.manifest import ManifestError, load_manifest

    bad = tmp_path / "bad.toml"
    bad.write_text('schema_version = 1\n[[source]]\npath = "../escape.md"\n', encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(bad)
    bad.write_text('schema_version = 1\n[[source]]\npath = "notes.txt"\n', encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(bad)


def test_manifest_rejects_unknown_fields_absolute_paths_and_symlink_escape(tmp_path: Path):
    from tracecite.evidence.manifest import ManifestError, load_manifest, resolve_sources

    bad = tmp_path / "bad.toml"
    bad.write_text('schema_version = 1\nunknown = true\n', encoding="utf-8")
    with pytest.raises(ManifestError, match="unknown field"):
        load_manifest(bad)
    bad.write_text(f'schema_version = 1\n[[source]]\npath = "{(tmp_path / "outside.md").as_posix()}"\n', encoding="utf-8")
    with pytest.raises(ManifestError, match="absolute"):
        load_manifest(bad)
    for absolute in ["C:/outside/report.md", r"C:\outside\report.md", "//server/share/report.md"]:
        bad.write_text(f"schema_version = 1\n[[source]]\npath = '{absolute}'\n", encoding="utf-8")
        with pytest.raises(ManifestError, match="absolute"):
            load_manifest(bad)

    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (root / "escape.md").symlink_to(outside)
    manifest = tmp_path / "manifest.toml"
    manifest.write_text('schema_version = 1\n[[source]]\npath = "escape.md"\n', encoding="utf-8")
    rules = load_manifest(manifest)
    selection = resolve_sources(root, rules)
    assert selection.available_paths == ()
    assert selection.missing_explicit_paths == ("escape.md",)


def test_manifest_duplicate_normalized_declarations_collapse_with_tracked_then_local_order(tmp_path: Path):
    from tracecite.evidence.manifest import merge_manifests

    tracked = tmp_path / "tracked.toml"
    local = tmp_path / "local.toml"
    tracked.write_text('schema_version = 1\n[[source]]\npath = "a.md"\norigin = "default"\n[[source]]\npath = "./a.md"\norigin = "default"\n[[include]]\nglob = "docs/*.md"\norigin = "default"\n', encoding="utf-8")
    local.write_text('schema_version = 1\n[[source]]\npath = "b.md"\norigin = "local"\n[[source]]\npath = "a.md"\norigin = "local"\n[[include]]\nglob = "docs/*.md"\norigin = "local"\n[[exclude]]\nglob = "drafts/*.md"\norigin = "local"\n', encoding="utf-8")
    rules = merge_manifests([tracked, local])
    assert rules.explicit_paths == ("a.md", "b.md")
    assert rules.include_globs == ("docs/*.md",)
    assert rules.exclude_globs == ("drafts/*.md",)


def test_combined_config_rules_preserve_origins_and_reject_conflicts(tmp_path: Path):
    from tracecite.evidence.manifest import ManifestError, load_manifest, merge_manifests

    default = tmp_path / "default.toml"
    local = tmp_path / "local.toml"
    default.write_text(
        'schema_version = 1\nroot = "."\ndatabase = "db.sqlite"\nmodel_cache_dir = "cache"\n'
        '[[source]]\npath = "docs/guide.md"\norigin = "default"\n'
        '[[include]]\nglob = "docs/**/*.md"\norigin = "default"\n',
        encoding="utf-8",
    )
    local.write_text(
        'schema_version = 1\n[[source]]\npath = "./docs/guide.md"\norigin = "local"\n'
        '[[exclude]]\nglob = "docs/drafts/**"\norigin = "local"\n',
        encoding="utf-8",
    )

    rules = merge_manifests([default, local])
    assert rules.explicit_paths == ("docs/guide.md",)
    assert rules.include_globs == ("docs/**/*.md",)
    assert rules.exclude_globs == ("docs/drafts/**",)
    assert rules.origins[("source", "docs/guide.md")] == "local"

    local.write_text('schema_version = 1\n[[source]]\npath = "docs/guide.md"\norigin = "custom"\n', encoding="utf-8")
    with pytest.raises(ManifestError, match="unsupported origin"):
        load_manifest(local)
    local.write_text('schema_version = 1\n[[source]]\npath = "docs/guide.md"\norigin = "local"\ntitle = "conflict"\n', encoding="utf-8")
    with pytest.raises(ManifestError, match="unknown field"):
        load_manifest(local)


def test_local_precedence_is_independent_of_declaration_order_and_origins_are_immutable(tmp_path: Path):
    from tracecite.evidence.manifest import load_manifest, merge_manifests

    default = tmp_path / "default.toml"
    local = tmp_path / "local.toml"
    default.write_text('schema_version = 1\n[[source]]\npath = "./same.md"\norigin = "default"\n', encoding="utf-8")
    local.write_text('schema_version = 1\n[[source]]\npath = "same.md"\norigin = "local"\n', encoding="utf-8")

    for paths in ([default, local], [local, default]):
        rules = merge_manifests(paths)
        assert rules.explicit_paths == ("same.md",)
        assert rules.origins[("source", "same.md")] == "local"
        with pytest.raises(TypeError):
            rules.origins[("source", "same.md")] = "default"

    for text in (
        'schema_version = 1\n[[source]]\npath = "same.md"\norigin = "default"\n[[source]]\npath = "./same.md"\norigin = "local"\n',
        'schema_version = 1\n[[source]]\npath = "same.md"\norigin = "local"\n[[source]]\npath = "./same.md"\norigin = "default"\n',
    ):
        one_file = tmp_path / "one-file.toml"
        one_file.write_text(text, encoding="utf-8")
        rules = load_manifest(one_file)
        assert rules.explicit_paths == ("same.md",)
        assert rules.origins[("source", "same.md")] == "local"


def test_exclusion_precedence_across_inline_and_manifest_rules(tmp_path: Path):
    from tracecite.evidence.manifest import merge_manifests

    inline = tmp_path / "inline.toml"
    manifest = tmp_path / "manifest.toml"
    inline.write_text('schema_version = 1\nroot = "."\ndatabase = "db.sqlite"\nmodel_cache_dir = "cache"\n[[include]]\nglob = "docs/**/*.md"\norigin = "default"\n', encoding="utf-8")
    manifest.write_text('schema_version = 1\n[[include]]\nglob = "docs/**/*.md"\n[[exclude]]\nglob = "docs/private/**"\n', encoding="utf-8")
    rules = merge_manifests([inline, manifest])
    assert rules.include_globs == ("docs/**/*.md",)
    assert rules.selects_path("docs/public/a.md")
    assert not rules.selects_path("docs/private/a.md")


def test_manifest_discovery_is_limited_to_declared_candidates(tmp_path: Path):
    from tracecite.evidence.manifest import merge_manifests, resolve_sources

    root = tmp_path / "root"
    (root / "docs").mkdir(parents=True)
    (root / "node_modules" / "deep").mkdir(parents=True)
    (root / "docs" / "keep.md").write_text("keep", encoding="utf-8")
    (root / "node_modules" / "deep" / "bad.md").write_text("bad", encoding="utf-8")
    manifest = tmp_path / "manifest.toml"
    manifest.write_text('schema_version = 1\n[[include]]\nglob = "docs/*.md"\n', encoding="utf-8")
    selection = resolve_sources(root, merge_manifests([manifest]))
    assert selection.available_paths == ("docs/keep.md",)
    assert "node_modules/deep/bad.md" not in selection.available_paths
