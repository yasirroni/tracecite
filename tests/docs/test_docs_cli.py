from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tracecite import cli


def test_docs_build_config_options_are_distinct_from_evidence_config() -> None:
    args = cli.build_parser().parse_args([
        "docs",
        "build",
        "docs",
        "--docs-config",
        "docs/tracecite.toml",
        "--repo-root",
        ".",
    ])
    assert args.docs_config == Path("docs/tracecite.toml")
    assert args.repo_root == Path(".")
    omitted = cli.build_parser().parse_args(["docs", "build", "docs"])
    assert omitted.repo_root == Path.cwd()
    assert isinstance(omitted.repo_root, Path)

    evidence = cli.build_parser().parse_args(["--config", "profile.toml", "doctor"])
    assert evidence.config == Path("profile.toml")


def test_docs_build_adapter_consumes_docs_config_without_reusing_evidence_config(tmp_path: Path) -> None:
    args = cli.build_parser().parse_args([
        "docs", "build", "docs", "--docs-config", "docs/tracecite.toml", "--repo-root", "."
    ])
    result = SimpleNamespace(
        selection=SimpleNamespace(variant="prose"),
        output_root=tmp_path / "build",
        retained_count=0,
        inspection=None,
    )
    with patch.object(cli, "load_docs_contract") as load, patch.object(cli, "build_docs", return_value=result) as build:
        assert cli._docs_build(args) == 0
    load.assert_called_once_with(Path("docs/tracecite.toml"), repo_root=Path("."))
    build.assert_called_once()
