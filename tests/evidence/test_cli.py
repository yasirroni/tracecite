"""CLI-level tests, including the exact invocation contract from the task
card ("Tool-project layout and invocation contract")."""

from __future__ import annotations

import subprocess
import sys
import os
import json
import importlib
from pathlib import Path
import pytest

from tracecite.evidence import cli
from tracecite.evidence import schema, sync as sync_module

from conftest import FakeEmbedder, build_pdf, write_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_corpus(tmp_path: Path):
    corpus_dir = tmp_path / "sources"
    corpus_dir.mkdir()
    build_pdf(
        corpus_dir / "doc.pdf",
        [["Report", "This report contains a distinctive sentence about renewable energy storage capacity."]],
    )
    manifest_path = tmp_path / "manifest.toml"
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    database_path = tmp_path / "runtime" / "knowledge.sqlite"
    return corpus_dir, manifest_path, database_path


def _fake_model(*args, **kwargs):
    return FakeEmbedder()


def _write_manifest(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _insert_source(database_path: Path, stored_path: str) -> None:
    conn = schema.connect(database_path)
    try:
        schema.ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO sources (
                path, source_type, language, canonical_url,
                capture_manifest_ref, sha256, size_bytes, mtime_ns,
                parser_name, parser_version, parser_config,
                chunker_name, chunker_version, chunker_config,
                normalisation_version, normalisation_config,
                indexed_at_utc, index_status
            ) VALUES (?, 'markdown', NULL, NULL, NULL, 'sha', 1, 1, 'parser', '1', '{}', 'chunker', '1', '{}', '1', '{}', 'now', 'ok')
            """,
            (stored_path,),
        )
        conn.commit()
    finally:
        conn.close()


def _source_paths(database_path: Path) -> list[str]:
    conn = schema.connect(database_path)
    try:
        schema.ensure_schema(conn)
        return [row["path"] for row in conn.execute("SELECT path FROM sources ORDER BY path").fetchall()]
    finally:
        conn.close()


def test_cli_sync_and_doctor_via_main(tmp_path, monkeypatch):
    corpus_dir, manifest_path, database_path = _make_corpus(tmp_path)
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)

    exit_code = cli.main(
        [
            "sync",
            "--root",
            str(corpus_dir),
            "--manifest",
            str(manifest_path),
            "--database",
            str(database_path),
        ]
    )
    assert exit_code == 0

    exit_code = cli.main(["doctor", "--database", str(database_path)])
    assert exit_code == 0


def test_cli_page_and_verify_quote(tmp_path, capsys, monkeypatch):
    corpus_dir, manifest_path, database_path = _make_corpus(tmp_path)
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)
    cli.main(
        [
            "sync",
            "--root",
            str(corpus_dir),
            "--manifest",
            str(manifest_path),
            "--database",
            str(database_path),
        ]
    )

    exit_code = cli.main(["page", "--database", str(database_path), "doc.pdf", "1"])
    captured = capsys.readouterr()
    assert exit_code == 0


def test_cli_verify_quote_exit_codes_and_json_contract(tmp_path, capsys, monkeypatch):
    corpus_dir, manifest_path, database_path = _make_corpus(tmp_path)
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)
    assert cli.main(
        [
            "sync",
            "--root",
            str(corpus_dir),
            "--manifest",
            str(manifest_path),
            "--database",
            str(database_path),
        ]
    ) == 0
    capsys.readouterr()

    cases = [
        (
            "This report contains a distinctive sentence about renewable energy storage capacity.",
            0,
            "exact",
        ),
        ("", 1, "structural-error"),
        ("quotation not present", 1, "not-found"),
    ]
    for quote, expected_exit, expected_status in cases:
        exit_code = cli.main(
            [
                "verify",
                "quote",
                "--root",
                str(corpus_dir),
                "--database",
                str(database_path),
                "doc.pdf",
                "1",
                quote,
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert exit_code == expected_exit
        assert payload["status"] == expected_status
        assert payload["quote"] == quote
        assert payload["citation_key"] is None
        assert payload["source_path"] == "doc.pdf"


def test_cli_page_and_quote_normalise_paths_and_reject_escapes(tmp_path, capsys, monkeypatch):
    corpus_dir, manifest_path, database_path = _make_corpus(tmp_path)
    outside = tmp_path / "outside.pdf"
    outside.write_text("outside", encoding="utf-8")
    (corpus_dir / "escape.pdf").symlink_to(outside)
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)
    assert cli.main(["sync", "--root", str(corpus_dir), "--manifest", str(manifest_path), "--database", str(database_path)]) == 0

    assert cli.main(["page", "--root", str(corpus_dir), "--database", str(database_path), "./doc.pdf", "1"]) == 0
    assert "renewable energy storage" in capsys.readouterr().out
    assert cli.main(["page", "--root", str(corpus_dir), "--database", str(database_path), "subdir\\..\\doc.pdf", "1"]) == 0
    assert "renewable energy storage" in capsys.readouterr().out
    assert cli.main([
        "verify", "quote", "--root", str(corpus_dir), "--database", str(database_path),
        "./doc.pdf", "1", "This report contains a distinctive sentence about renewable energy storage capacity."
    ]) == 0

    for bad_path in ["../outside.pdf", str(outside), "escape.pdf"]:
        exit_code = cli.main(["page", "--root", str(corpus_dir), "--database", str(database_path), bad_path, "1"])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "path-error" in captured.err
    exit_code = cli.main(
        [
            "verify",
            "quote",
            "--database",
            str(database_path),
            "doc.pdf",
            "1",
            "This report contains a distinctive sentence about renewable energy storage capacity.",
        ]
    )
    assert exit_code == 0


def test_cli_search_returns_json(tmp_path, capsys, monkeypatch):
    corpus_dir, manifest_path, database_path = _make_corpus(tmp_path)
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)
    cli.main(
        [
            "sync",
            "--root",
            str(corpus_dir),
            "--manifest",
            str(manifest_path),
            "--database",
            str(database_path),
        ]
    )
    exit_code = cli.main(
        [
            "search",
            "--database",
            str(database_path),
            "renewable storage capacity",
            "--limit",
            "5",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "renewable energy storage" in captured.out


def test_cli_search_percentage_query_keeps_json_on_stdout(tmp_path, capsys, monkeypatch):
    corpus_dir, manifest_path, database_path = _make_corpus(tmp_path)
    captured_queries = []

    class CapturingEmbedder(FakeEmbedder):
        def embed(self, texts):
            captured_queries.extend(texts)
            return super().embed(texts)

    monkeypatch.setattr(sync_module, "EmbeddingModel", lambda *args, **kwargs: CapturingEmbedder())
    assert cli.main(
        [
            "sync",
            "--root",
            str(corpus_dir),
            "--manifest",
            str(manifest_path),
            "--database",
            str(database_path),
        ]
    ) == 0
    capsys.readouterr()

    query = "10%, 50%, and 90%"
    assert cli.main(["search", "--database", str(database_path), query]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert isinstance(payload, list)
    assert query in captured_queries
    assert "FTS5 lexical search" in captured.err


def test_module_invocation_contract_via_subprocess():
    """TraceCite runs through the package entry point, not direct-script path hacks."""

    workspace_python = Path(sys.executable)

    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    result = subprocess.run(
        [
            str(workspace_python),
            "-m",
            "tracecite",
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "usage: tracecite" in result.stdout


def test_prune_preview_uses_globs_and_vanished_checkout_without_mutating(tmp_path, capsys):
    database_path = tmp_path / "tracecite.sqlite"
    _insert_source(database_path, "checkout/docs/kept.md")
    _insert_source(database_path, "checkout/docs/pruned.md")
    manifest_path = _write_manifest(
        tmp_path / "manifest.toml",
        'schema_version = 1\n\n[[include]]\nglob = "checkout/docs/kept.md"\n',
    )

    exit_code = cli.main(["prune", "--database", str(database_path), "--manifest", str(manifest_path)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "preview",
        "selected_count": 1,
        "planned_count": 1,
        "paths": ["checkout/docs/pruned.md"],
        "applied": False,
        "database_committed": False,
        "cleanup_warnings": [],
    }
    assert _source_paths(database_path) == ["checkout/docs/kept.md", "checkout/docs/pruned.md"]


def test_cli_sync_prints_structured_missing_and_unmatched_warnings(tmp_path, capsys, monkeypatch):
    root = tmp_path / "sources"
    root.mkdir()
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text('schema_version = 1\n[[source]]\npath = "missing.pdf"\n[[include]]\nglob = "reports/*.md"\n', encoding="utf-8")
    database_path = tmp_path / "tracecite.sqlite"
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)
    exit_code = cli.main(["sync", "--root", str(root), "--manifest", str(manifest_path), "--database", str(database_path)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "selected-missing: ['missing.pdf']" in out
    assert "unmatched-globs: ['reports/*.md']" in out


def test_prune_apply_honours_layered_local_exclusion(tmp_path, capsys):
    database_path = tmp_path / "tracecite.sqlite"
    _insert_source(database_path, "docs/keep.md")
    _insert_source(database_path, "docs/local-excluded.md")
    tracked = _write_manifest(
        tmp_path / "tracked.toml",
        'schema_version = 1\n\n[[include]]\nglob = "docs/*.md"\n',
    )
    local = _write_manifest(
        tmp_path / "local.toml",
        'schema_version = 1\n\n[[exclude]]\nglob = "docs/local-excluded.md"\n',
    )

    exit_code = cli.main(
        [
            "prune",
            "--database",
            str(database_path),
            "--manifest",
            str(tracked),
            "--manifest",
            str(local),
            "--apply",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "applied",
        "selected_count": 1,
        "planned_count": 1,
        "paths": ["docs/local-excluded.md"],
        "applied": True,
        "database_committed": True,
        "cleanup_warnings": [],
    }
    assert _source_paths(database_path) == ["docs/keep.md"]


def test_prune_apply_rolls_back_on_failure(tmp_path, monkeypatch):
    database_path = tmp_path / "tracecite.sqlite"
    _insert_source(database_path, "docs/keep.md")
    _insert_source(database_path, "docs/remove.md")
    manifest_path = _write_manifest(tmp_path / "manifest.toml", 'schema_version = 1\n[[source]]\npath = "docs/keep.md"\n')

    def fail_touch_config(conn):
        raise RuntimeError("injected prune failure")

    monkeypatch.setattr(sync_module.schema, "touch_config", fail_touch_config)
    active_sync_module = importlib.import_module("tracecite.evidence.sync")
    monkeypatch.setattr(active_sync_module.schema, "touch_config", fail_touch_config)

    try:
        cli.main(["prune", "--database", str(database_path), "--manifest", str(manifest_path), "--apply"])
    except RuntimeError as exc:
        assert "injected prune failure" in str(exc)
    else:
        raise AssertionError("expected injected prune failure")

    assert _source_paths(database_path) == ["docs/keep.md", "docs/remove.md"]


def test_prune_requires_nonempty_effective_rules(tmp_path, capsys):
    database_path = tmp_path / "tracecite.sqlite"
    _insert_source(database_path, "docs/remove.md")
    empty_manifest = _write_manifest(tmp_path / "empty.toml", "schema_version = 1\n")

    for args in (
        ["prune", "--database", str(database_path), "--manifest", str(empty_manifest)],
        ["prune", "--database", str(database_path), "--manifest", str(empty_manifest), "--apply"],
    ):
        assert cli.main(args) == 2
        captured = capsys.readouterr()
        assert "at least one" in captured.err
        assert _source_paths(database_path) == ["docs/remove.md"]


def test_prune_rejects_exclude_only_and_zero_match_selection(tmp_path, capsys):
    database_path = tmp_path / "tracecite.sqlite"
    _insert_source(database_path, "docs/remove.md")
    exclude_only = _write_manifest(
        tmp_path / "exclude-only.toml",
        'schema_version = 1\n[[exclude]]\nglob = "docs/keep.md"\n',
    )
    zero_match = _write_manifest(
        tmp_path / "zero-match.toml",
        'schema_version = 1\n[[include]]\nglob = "other/*.md"\n',
    )

    assert cli.main(["prune", "--database", str(database_path), "--manifest", str(exclude_only)]) == 2
    assert "positive source/include" in capsys.readouterr().err
    assert _source_paths(database_path) == ["docs/remove.md"]

    assert cli.main(["prune", "--database", str(database_path), "--manifest", str(zero_match)]) == 2
    assert "matched zero indexed sources" in capsys.readouterr().err
    assert _source_paths(database_path) == ["docs/remove.md"]


def test_prune_all_requires_explicit_flag_and_reports_counts(tmp_path, capsys):
    database_path = tmp_path / "tracecite.sqlite"
    _insert_source(database_path, "docs/one.md")
    _insert_source(database_path, "docs/two.md")

    assert cli.main(["prune", "--database", str(database_path), "--all"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "preview",
        "selected_count": 0,
        "planned_count": 2,
        "paths": ["docs/one.md", "docs/two.md"],
        "applied": False,
        "database_committed": False,
        "cleanup_warnings": [],
    }
    assert _source_paths(database_path) == ["docs/one.md", "docs/two.md"]


def test_read_commands_reject_missing_database_without_creation(tmp_path, capsys):
    database_path = tmp_path / "missing-parent" / "missing.sqlite"
    report = tmp_path / "report.md"
    report.write_text("# Report\n", encoding="utf-8")
    manifest = _write_manifest(tmp_path / "manifest.toml", 'schema_version = 1\n[[include]]\nglob = "*.md"\n')

    commands = [
        ["search", "--database", str(database_path), "query"],
        ["page", "--database", str(database_path), "doc.md", "1"],
        ["verify", "quote", "--database", str(database_path), "doc.md", "1", "quote"],
        ["verify", "report", "--database", str(database_path), str(report)],
        ["doctor", "--database", str(database_path)],
        ["prune", "--database", str(database_path), "--manifest", str(manifest)],
        ["prune", "--database", str(database_path), "--manifest", str(manifest), "--apply"],
    ]

    for command in commands:
        assert cli.main(command) == 2
        captured = capsys.readouterr()
        assert "database does not exist" in captured.err
        assert not database_path.exists()
        assert not database_path.parent.exists()


def test_cli_verify_report_emits_citation_binding(tmp_path, capsys):
    root = tmp_path / "sources"
    root.mkdir()
    source_path = root / "doc.md"
    source_path.write_text("Evidence sentence retained on page one.\n", encoding="utf-8")
    database_path = tmp_path / "tracecite.sqlite"
    _insert_source(database_path, "doc.md")
    conn = schema.connect(database_path)
    try:
        source_pk = conn.execute("SELECT source_pk FROM sources WHERE path = 'doc.md'").fetchone()[0]
        conn.execute(
            """
            INSERT INTO pages (
                source_pk, physical_page, printed_label, text,
                extraction_method, extraction_status, section_candidates, layout_json
            ) VALUES (?, 1, NULL, ?, 'test', 'ok', '[]', NULL)
            """,
            (source_pk, "Evidence sentence retained on page one."),
        )
        conn.commit()
    finally:
        conn.close()

    report_path = root / "report.md"
    report_path.write_text(
        "Evidence [source][A].\n\n"
        '> "Evidence sentence retained on page one."\n\n'
        "[A]: doc.md#page=1\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "verify",
            "report",
            "--root",
            str(root),
            "--database",
            str(database_path),
            str(report_path),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["quote_results"] == [
        {
            "status": "exact",
            "page": 1,
            "quote": "Evidence sentence retained on page one.",
            "citation_key": "A",
            "source_path": "doc.md",
        }
    ]


def test_prune_apply_reports_postcommit_cleanup_warning(tmp_path, capsys, monkeypatch):
    database_path = tmp_path / "tracecite.sqlite"
    _insert_source(database_path, "docs/keep.md")
    _insert_source(database_path, "docs/remove.md")
    manifest_path = _write_manifest(
        tmp_path / "manifest.toml",
        'schema_version = 1\n[[source]]\npath = "docs/keep.md"\n',
    )

    def fail_cleanup(conn, database):
        raise RuntimeError("injected cleanup failure")

    monkeypatch.setattr(sync_module, "cleanup_asset_generations", fail_cleanup)
    exit_code = cli.main(
        [
            "prune",
            "--database",
            str(database_path),
            "--manifest",
            str(manifest_path),
            "--apply",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 3
    assert payload["status"] == "applied-with-cleanup-warnings"
    assert payload["database_committed"] is True
    assert payload["cleanup_warnings"] == [
        "failed to clean unreferenced asset generations: injected cleanup failure"
    ]
    assert _source_paths(database_path) == ["docs/keep.md"]
