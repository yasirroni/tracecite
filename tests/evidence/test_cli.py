"""CLI-level tests, including the package invocation contract."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from conftest import FakeEmbedder, build_pdf, insert_source, write_manifest

from tracecite import cli
from tracecite.evidence import schema
from tracecite.evidence import sync as sync_module

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_corpus(tmp_path: Path):
    corpus_dir = tmp_path / "sources"
    corpus_dir.mkdir()
    build_pdf(
        corpus_dir / "doc.pdf",
        [
            [
                "Report",
                "This report contains a distinctive sentence about renewable energy storage capacity.",
            ]
        ],
    )
    manifest_path = tmp_path / "manifest.toml"
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    database_path = tmp_path / "runtime" / "knowledge.sqlite"
    return corpus_dir, manifest_path, database_path


def _sync(root: Path, manifest_path: Path, database_path: Path) -> int:
    return cli.main(
        [
            "sync",
            "--root",
            str(root),
            "--manifest",
            str(manifest_path),
            "--database",
            str(database_path),
        ]
    )


def _fake_model(*args, **kwargs):
    return FakeEmbedder()


def _write_manifest(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _insert_source(database_path: Path, stored_path: str) -> None:
    with closing(schema.connect(database_path)) as conn:
        schema.ensure_schema(conn)
        insert_source(conn, stored_path, "markdown")
        conn.commit()


def _make_root(tmp_path: Path, *paths: str) -> Path:
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    for path in paths:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("# Source\n", encoding="utf-8")
    return root


def _source_paths(database_path: Path) -> list[str]:
    with closing(schema.connect(database_path)) as conn:
        schema.ensure_schema(conn)
        return [
            row["path"]
            for row in conn.execute("SELECT path FROM sources ORDER BY path").fetchall()
        ]


def test_cli_sync_and_doctor_via_main(tmp_path, monkeypatch):
    corpus_dir, manifest_path, database_path = _make_corpus(tmp_path)
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)

    exit_code = _sync(corpus_dir, manifest_path, database_path)
    assert exit_code == 0

    exit_code = cli.main(["doctor", "--database", str(database_path)])
    assert exit_code == 0


def test_cli_verify_quote_exit_codes_and_json_contract(tmp_path, capsys, monkeypatch):
    corpus_dir, manifest_path, database_path = _make_corpus(tmp_path)
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)
    assert _sync(corpus_dir, manifest_path, database_path) == 0
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


def test_cli_page_and_quote_normalise_paths_and_reject_escapes(
    tmp_path, capsys, monkeypatch
):
    corpus_dir, manifest_path, database_path = _make_corpus(tmp_path)
    outside = tmp_path / "outside.pdf"
    outside.write_text("outside", encoding="utf-8")
    (corpus_dir / "escape.pdf").symlink_to(outside)
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)
    assert _sync(corpus_dir, manifest_path, database_path) == 0

    assert (
        cli.main(
            [
                "page",
                "--root",
                str(corpus_dir),
                "--database",
                str(database_path),
                "./doc.pdf",
                "1",
            ]
        )
        == 0
    )
    assert "renewable energy storage" in capsys.readouterr().out
    assert (
        cli.main(
            [
                "page",
                "--root",
                str(corpus_dir),
                "--database",
                str(database_path),
                "subdir\\..\\doc.pdf",
                "1",
            ]
        )
        == 0
    )
    assert "renewable energy storage" in capsys.readouterr().out
    assert (
        cli.main(
            [
                "verify",
                "quote",
                "--root",
                str(corpus_dir),
                "--database",
                str(database_path),
                "./doc.pdf",
                "1",
                "This report contains a distinctive sentence about renewable energy storage capacity.",
            ]
        )
        == 0
    )

    for bad_path in ["../outside.pdf", str(outside), "escape.pdf"]:
        exit_code = cli.main(
            [
                "page",
                "--root",
                str(corpus_dir),
                "--database",
                str(database_path),
                bad_path,
                "1",
            ]
        )
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
    _sync(corpus_dir, manifest_path, database_path)
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


def test_cli_search_percentage_query_keeps_json_on_stdout(
    tmp_path, capsys, monkeypatch
):
    corpus_dir, manifest_path, database_path = _make_corpus(tmp_path)
    captured_queries = []

    class CapturingEmbedder(FakeEmbedder):
        def embed(self, texts):
            captured_queries.extend(texts)
            return super().embed(texts)

    monkeypatch.setattr(
        sync_module, "EmbeddingModel", lambda *args, **kwargs: CapturingEmbedder()
    )
    assert _sync(corpus_dir, manifest_path, database_path) == 0
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

    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src"), "PYTHON_COLORS": "0"}
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
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "usage: tracecite" in result.stdout


def test_prune_preview_uses_globs_without_mutating(tmp_path, capsys):
    database_path = tmp_path / "tracecite.sqlite"
    _insert_source(database_path, "checkout/docs/kept.md")
    _insert_source(database_path, "checkout/docs/pruned.md")
    root = _make_root(tmp_path, "checkout/docs/kept.md", "checkout/docs/pruned.md")
    manifest_path = _write_manifest(
        tmp_path / "manifest.toml",
        'schema_version = 1\n\n[[include]]\nglob = "checkout/docs/kept.md"\n',
    )

    exit_code = cli.main(
        [
            "prune",
            "--root",
            str(root),
            "--database",
            str(database_path),
            "--manifest",
            str(manifest_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "preview",
        "selected_count": 1,
        "planned_count": 1,
        "paths": ["checkout/docs/pruned.md"],
        "missing_paths": [],
        "applied": False,
        "database_committed": False,
        "cleanup_warnings": [],
    }
    assert _source_paths(database_path) == [
        "checkout/docs/kept.md",
        "checkout/docs/pruned.md",
    ]


def test_cli_sync_prints_structured_missing_and_unmatched_warnings(
    tmp_path, capsys, monkeypatch
):
    root = tmp_path / "sources"
    root.mkdir()
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(
        'schema_version = 1\n[[source]]\npath = "missing.pdf"\n[[include]]\nglob = "reports/*.md"\n',
        encoding="utf-8",
    )
    database_path = tmp_path / "tracecite.sqlite"
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)
    exit_code = _sync(root, manifest_path, database_path)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "selected-missing: 1\n  missing.pdf\n" in captured.out
    assert "missing-sources: 1\n  missing.pdf\n" in captured.out
    assert "unmatched-globs: 1\n  reports/*.md\n" in captured.out
    assert "missing.pdf" in captured.err


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

    root = _make_root(tmp_path, "docs/keep.md", "docs/local-excluded.md")

    exit_code = cli.main(
        [
            "prune",
            "--root",
            str(root),
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
        "missing_paths": [],
        "applied": True,
        "database_committed": True,
        "cleanup_warnings": [],
    }
    assert _source_paths(database_path) == ["docs/keep.md"]


def test_prune_apply_rolls_back_on_failure(tmp_path, capsys, monkeypatch):
    database_path = tmp_path / "tracecite.sqlite"
    _insert_source(database_path, "docs/keep.md")
    _insert_source(database_path, "docs/remove.md")
    manifest_path = _write_manifest(
        tmp_path / "manifest.toml",
        'schema_version = 1\n[[source]]\npath = "docs/keep.md"\n',
    )

    def fail_touch_config(conn):
        raise RuntimeError("injected prune failure")

    monkeypatch.setattr(sync_module.schema, "touch_config", fail_touch_config)
    root = _make_root(tmp_path, "docs/keep.md")

    assert (
        cli.main(
            [
                "prune",
                "--root",
                str(root),
                "--database",
                str(database_path),
                "--manifest",
                str(manifest_path),
                "--apply",
            ]
        )
        == 2
    )
    assert "injected prune failure" in capsys.readouterr().err
    assert _source_paths(database_path) == ["docs/keep.md", "docs/remove.md"]


def test_prune_requires_nonempty_effective_rules(tmp_path, capsys):
    database_path = tmp_path / "tracecite.sqlite"
    _insert_source(database_path, "docs/remove.md")
    empty_manifest = _write_manifest(tmp_path / "empty.toml", "schema_version = 1\n")

    for args in (
        ["prune", "--database", str(database_path), "--manifest", str(empty_manifest)],
        [
            "prune",
            "--database",
            str(database_path),
            "--manifest",
            str(empty_manifest),
            "--apply",
        ],
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

    assert (
        cli.main(
            ["prune", "--database", str(database_path), "--manifest", str(exclude_only)]
        )
        == 2
    )
    assert "positive source/include" in capsys.readouterr().err
    assert _source_paths(database_path) == ["docs/remove.md"]

    assert (
        cli.main(
            [
                "prune",
                "--root",
                str(tmp_path),
                "--database",
                str(database_path),
                "--manifest",
                str(zero_match),
            ]
        )
        == 2
    )
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
        "missing_paths": [],
        "applied": False,
        "database_committed": False,
        "cleanup_warnings": [],
    }
    assert _source_paths(database_path) == ["docs/one.md", "docs/two.md"]


def test_read_commands_reject_missing_database_without_creation(tmp_path, capsys):
    database_path = tmp_path / "missing-parent" / "missing.sqlite"
    report = tmp_path / "report.md"
    report.write_text("# Report\n", encoding="utf-8")
    manifest = _write_manifest(
        tmp_path / "manifest.toml", 'schema_version = 1\n[[include]]\nglob = "*.md"\n'
    )

    commands = [
        ["search", "--database", str(database_path), "query"],
        ["page", "--database", str(database_path), "doc.md", "1"],
        ["verify", "quote", "--database", str(database_path), "doc.md", "1", "quote"],
        ["verify", "report", "--database", str(database_path), str(report)],
        ["doctor", "--database", str(database_path)],
        [
            "prune",
            "--root",
            str(tmp_path),
            "--database",
            str(database_path),
            "--manifest",
            str(manifest),
        ],
        [
            "prune",
            "--root",
            str(tmp_path),
            "--database",
            str(database_path),
            "--manifest",
            str(manifest),
            "--apply",
        ],
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
    source_path.write_text(
        "Evidence sentence retained on page one.\n", encoding="utf-8"
    )
    database_path = tmp_path / "tracecite.sqlite"
    _insert_source(database_path, "doc.md")
    with closing(schema.connect(database_path)) as conn:
        source_pk = conn.execute(
            "SELECT source_pk FROM sources WHERE path = 'doc.md'"
        ).fetchone()[0]
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
    root = _make_root(tmp_path, "docs/keep.md")
    exit_code = cli.main(
        [
            "prune",
            "--root",
            str(root),
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


def test_commands_report_unreadable_database_in_one_line(tmp_path, capsys, monkeypatch):
    corpus_dir, manifest_path, database_path = _make_corpus(tmp_path)
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)
    assert _sync(corpus_dir, manifest_path, database_path) == 0
    not_sqlite = tmp_path / "not-sqlite.sqlite"
    not_sqlite.write_bytes(b"plain bytes, not an SQLite file\n" * 200)
    truncated = tmp_path / "truncated.sqlite"
    truncated.write_bytes(database_path.read_bytes()[:4096])
    capsys.readouterr()

    for bad_database in (not_sqlite, truncated):
        commands = [
            ["doctor"],
            ["search", "renewable"],
            ["page", "doc.pdf", "1"],
            ["verify", "quote", "doc.pdf", "1", "renewable"],
            ["prune", "--manifest", str(manifest_path)],
            ["sync", "--manifest", str(manifest_path)],
        ]
        for command in commands:
            exit_code = cli.main(
                [
                    *command,
                    "--root",
                    str(corpus_dir),
                    "--database",
                    str(bad_database),
                ]
            )
            err = capsys.readouterr().err
            assert exit_code == 2, command
            assert str(bad_database) in err
            assert len(err.strip().splitlines()) == 1


def test_cli_json_output_keeps_non_ascii_characters(tmp_path, capsys, monkeypatch):
    corpus_dir = tmp_path / "sources"
    corpus_dir.mkdir()
    build_pdf(corpus_dir / "doc.pdf", [["Übersicht", "Die Übersicht nennt Köln."]])
    manifest_path = write_manifest(tmp_path / "manifest.toml", {"doc.pdf": "doc.pdf"})
    database_path = tmp_path / "runtime" / "knowledge.sqlite"
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)
    assert _sync(corpus_dir, manifest_path, database_path) == 0
    capsys.readouterr()

    for command in (
        ["search", "Köln"],
        ["page", "doc.pdf", "1", "--format", "json"],
        ["verify", "quote", "doc.pdf", "1", "Die Übersicht nennt Köln."],
    ):
        exit_code = cli.main(
            [*command, "--root", str(corpus_dir), "--database", str(database_path)]
        )
        out = capsys.readouterr().out
        assert exit_code == 0, command
        assert "Köln" in out
        assert "\\u00f6" not in out


def test_cli_sync_lists_items_one_per_line_and_supports_json(
    tmp_path, capsys, monkeypatch
):
    corpus_dir, manifest_path, database_path = _make_corpus(tmp_path)
    (corpus_dir / "notes.md").write_text("# Notes\n\nA short note.\n", encoding="utf-8")
    manifest_path.write_text(
        'schema_version = 1\n[[include]]\nglob = "*"\n', encoding="utf-8"
    )
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)

    assert _sync(corpus_dir, manifest_path, database_path) == 0
    out = capsys.readouterr().out
    assert "added: 2\n  doc.pdf\n  notes.md\n" in out
    assert "reparsed: 0\n" in out
    assert "[" not in out and "(" not in out

    exit_code = cli.main(
        [
            "sync",
            "--root",
            str(corpus_dir),
            "--manifest",
            str(manifest_path),
            "--database",
            str(database_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["sources_added"] == []
    assert payload["sources_unchanged"] == ["doc.pdf", "notes.md"]


def test_cli_sync_without_positive_rule_fails_before_creating_database(
    tmp_path, capsys
):
    root = tmp_path / "sources"
    root.mkdir()
    database_path = tmp_path / "runtime" / "knowledge.sqlite"
    for text in (
        "schema_version = 1\n",
        'schema_version = 1\n[[exclude]]\nglob = "*.md"\n',
    ):
        manifest_path = _write_manifest(tmp_path / "manifest.toml", text)
        assert _sync(root, manifest_path, database_path) == 2
        assert "[[source]]" in capsys.readouterr().err
        assert not database_path.parent.exists()


def test_cli_sync_names_the_source_that_cannot_be_parsed(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)
    for name, content in (
        ("papers/random.pdf", os.urandom(4096)),
        ("papers/truncated.pdf", b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog"),
        ("notes/latin1.md", "Café notes\n".encode("latin-1")),
    ):
        root = tmp_path / name.replace("/", "-")
        (root / name).parent.mkdir(parents=True)
        (root / name).write_bytes(content)
        manifest_path = write_manifest(tmp_path / "manifest.toml", {name: name})
        database_path = root.parent / f"{root.name}.sqlite"

        exit_code = _sync(root, manifest_path, database_path)
        err = capsys.readouterr().err
        assert exit_code == 2
        assert name in err
        assert ".tracecite-source-snapshots" not in err
        assert len(err.strip().splitlines()) == 1


def test_cli_sync_names_the_source_whose_pages_cannot_be_rendered(
    tmp_path, capsys, monkeypatch
):
    corpus_dir, manifest_path, database_path = _make_corpus(tmp_path)
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)

    def fail_render(path, physical_page):
        raise RuntimeError(f"cannot render page {physical_page} of '{path}'")

    monkeypatch.setattr(sync_module.pdf_parser, "render_page", fail_render)

    assert _sync(corpus_dir, manifest_path, database_path) == 2
    err = capsys.readouterr().err
    assert "doc.pdf" in err
    assert ".tracecite-source-snapshots" not in err


def test_prune_removes_selected_sources_whose_files_are_gone(
    tmp_path, capsys, monkeypatch
):
    root = _make_root(tmp_path, "papers/kept.md", "papers/scanned.md")
    manifest_path = _write_manifest(
        tmp_path / "manifest.toml",
        'schema_version = 1\n[[include]]\nglob = "papers/*.md"\n',
    )
    database_path = tmp_path / "tracecite.sqlite"
    monkeypatch.setattr(sync_module, "EmbeddingModel", _fake_model)
    assert _sync(root, manifest_path, database_path) == 0
    (root / "papers" / "scanned.md").unlink()
    capsys.readouterr()

    prune = [
        "prune",
        "--root",
        str(root),
        "--database",
        str(database_path),
        "--manifest",
        str(manifest_path),
    ]
    assert cli.main(prune) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["paths"] == ["papers/scanned.md"]
    assert preview["missing_paths"] == ["papers/scanned.md"]
    assert preview["selected_count"] == 1

    assert cli.main([*prune, "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "applied"
    assert _source_paths(database_path) == ["papers/kept.md"]

    # Rule matches, not existing files, decide the zero-match guard, so a
    # selection whose files are all gone can still be pruned.
    (root / "papers" / "kept.md").unlink()
    assert cli.main([*prune, "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["paths"] == ["papers/kept.md"]
    assert _source_paths(database_path) == []


def test_prune_requires_a_root_unless_pruning_everything(tmp_path, capsys):
    database_path = tmp_path / "tracecite.sqlite"
    _insert_source(database_path, "docs/one.md")
    manifest_path = _write_manifest(
        tmp_path / "manifest.toml",
        'schema_version = 1\n[[include]]\nglob = "docs/*.md"\n',
    )

    exit_code = cli.main(
        ["prune", "--database", str(database_path), "--manifest", str(manifest_path)]
    )

    assert exit_code == 2
    assert "--root" in capsys.readouterr().err
    assert _source_paths(database_path) == ["docs/one.md"]
    assert cli.main(["prune", "--database", str(database_path), "--all"]) == 0
