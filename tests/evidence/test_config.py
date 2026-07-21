from __future__ import annotations

from pathlib import Path

import pytest


def test_profile_values_and_inline_rules_are_relative_to_config_file(tmp_path: Path):
    from tracecite.evidence.config import discover_profile, load_profile

    root = tmp_path / "repo"
    (root / "nested").mkdir(parents=True)
    profile_path = root / "tracecite.toml"
    profile_path.write_text(
        """
schema_version = 1
root = "."
database = "artifacts/tracecite.sqlite"
model_cache_dir = "artifacts/model-cache"
[[source]]
path = "README.md"
origin = "default"
[[include]]
glob = "docs/**/*.md"
origin = "local"
[[exclude]]
glob = "docs/build/**"
origin = "default"
""".strip(),
        encoding="utf-8",
    )
    assert discover_profile(root / "nested") is None
    assert discover_profile(root / "nested", profile_path) == profile_path
    profile = load_profile(profile_path)
    assert profile.root == root
    assert profile.database == root / "artifacts" / "tracecite.sqlite"
    assert profile.model_cache_dir == root / "artifacts" / "model-cache"
    assert profile.manifests == (profile_path,)
    assert profile.rules.explicit_paths == ("README.md",)
    assert profile.rules.include_globs == ("docs/**/*.md",)
    assert profile.rules.exclude_globs == ("docs/build/**",)


def test_config_rejects_legacy_manifest_list_unknown_fields_and_local_scalars(tmp_path: Path):
    from tracecite.evidence.config import ConfigError, load_profile

    config = tmp_path / "tracecite.toml"
    config.write_text(
        'schema_version = 1\nroot = "."\ndatabase = "db.sqlite"\nmodel_cache_dir = "cache"\nmanifests = []\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="unknown field"):
        load_profile(config)


def test_config_rejects_malformed_values_and_duplicate_default_scalars(tmp_path: Path):
    from tracecite.evidence.config import ConfigError, load_profile

    config = tmp_path / "tracecite.toml"
    config.write_text(
        'schema_version = 1\nroot = ["not", "a", "string"]\ndatabase = "db.sqlite"\nmodel_cache_dir = "cache"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="root"):
        load_profile(config)

    original = b'schema_version = 1\nroot = "."\nroot = "duplicate"\ndatabase = "db.sqlite"\nmodel_cache_dir = "cache"\n'
    config.write_bytes(original)
    with pytest.raises(ConfigError, match="duplicate|Cannot overwrite"):
        load_profile(config)
    assert config.read_bytes() == original

    config.write_text(
        'schema_version = 1\nroot = "."\ndatabase = "db.sqlite"\nmodel_cache_dir = "cache"\n[[source]]\npath = "README.md"\norigin = "local"\nroot = "other"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="unknown field"):
        load_profile(config)
