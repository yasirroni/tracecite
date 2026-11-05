from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tracecite import cli


def test_docs_build_config_options_are_distinct_from_evidence_config() -> None:
    args = cli.build_parser().parse_args(
        [
            "docs",
            "build",
            "docs",
            "--docs-config",
            "docs/tracecite.toml",
            "--repo-root",
            ".",
        ]
    )
    assert args.docs_config == Path("docs/tracecite.toml")
    assert args.repo_root == Path(".")
    omitted = cli.build_parser().parse_args(["docs", "build", "docs"])
    assert omitted.repo_root == Path.cwd()
    assert isinstance(omitted.repo_root, Path)

    evidence = cli.build_parser().parse_args(["--config", "profile.toml", "doctor"])
    assert evidence.config == Path("profile.toml")


def test_docs_stage_options_are_explicit() -> None:
    args = cli.build_parser().parse_args(
        [
            "docs",
            "stage",
            "--docs-config",
            "docs/tracecite.toml",
            "--repo-root",
            ".",
            "--target",
            "public",
        ]
    )
    assert args.docs_command == "stage"
    assert args.target == "public"


def test_docs_modes_require_config_and_accept_repo_root() -> None:
    for name in ("author", "check"):
        args = cli.build_parser().parse_args(
            ["docs", name, "--docs-config", "docs/tracecite.toml", "--repo-root", "."]
        )
        assert args.docs_command == name
        assert args.docs_config == Path("docs/tracecite.toml")
        assert args.repo_root == Path(".")


def test_docs_build_adapter_consumes_docs_config_without_reusing_evidence_config(
    tmp_path: Path,
) -> None:
    args = cli.build_parser().parse_args(
        [
            "docs",
            "build",
            "docs",
            "--docs-config",
            "docs/tracecite.toml",
            "--repo-root",
            ".",
        ]
    )
    result = SimpleNamespace(
        selection=SimpleNamespace(variant="prose"),
        output_root=tmp_path / "build",
        retained_count=0,
        inspection=None,
    )
    with (
        patch.object(cli, "load_docs_contract") as load,
        patch.object(cli, "build_docs", return_value=result) as build,
    ):
        assert cli._docs_build(args) == 0
    load.assert_called_once_with(Path("docs/tracecite.toml"), repo_root=Path("."))
    build.assert_called_once()


def test_docs_mode_dispatch_passes_contract_arguments_and_status(capsys) -> None:
    args = cli.build_parser().parse_args(
        ["docs", "check", "--docs-config", "config.toml", "--repo-root", "repo"]
    )
    contract = object()
    ok = SimpleNamespace(
        mode="check", ok=True, manifest_path=Path("manifest"), diagnostics=()
    )
    with (
        patch.object(cli, "load_docs_contract", return_value=contract) as load,
        patch.object(cli, "check_docs", return_value=ok) as operation,
    ):
        assert cli._docs_mode(args, cli.check_docs) == 0
    load.assert_called_once_with(Path("config.toml"), repo_root=Path("repo"))
    operation.assert_called_once_with(
        contract, config_path=Path("config.toml"), repo_root=Path("repo")
    )
    assert "Documentation mode: check" in capsys.readouterr().out

    stale = SimpleNamespace(
        mode="check",
        ok=False,
        manifest_path=Path("manifest"),
        diagnostics=("stale: docs/x.md",),
    )
    with (
        patch.object(cli, "load_docs_contract", return_value=contract),
        patch.object(cli, "check_docs", return_value=stale),
    ):
        assert cli._docs_mode(args, cli.check_docs) == 1
    assert "stale: docs/x.md" in capsys.readouterr().err


def test_docs_index_exits_1_and_names_a_skipped_source(capsys) -> None:
    from tracecite.evidence.sync import SyncReport

    args = cli.build_parser().parse_args(
        ["docs", "index", "--docs-config", "config.toml", "--repo-root", "repo"]
    )
    report = SyncReport(skipped_sources={"bad.md": "cannot parse: invalid UTF-8"})
    result = SimpleNamespace(
        profile=SimpleNamespace(input_root=Path("in"), database_path=Path("db")),
        tables_normalized=0,
        sync_report=report,
    )
    with (
        patch.object(cli, "load_docs_contract"),
        patch.object(cli, "sync_docs_index", return_value=result),
    ):
        assert cli._docs_index(args) == 1
    out = capsys.readouterr().out
    assert "status: incomplete\n" in out
    assert "skipped: bad.md: cannot parse: invalid UTF-8\n" in out
