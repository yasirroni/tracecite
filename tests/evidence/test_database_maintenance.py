from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def make_db(path: Path, *, bloat: bool = False, vectors: bool = True) -> Path:
    from tracecite.evidence import schema, vector_backend

    conn = schema.connect(path)
    try:
        schema.ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO sources (
                path, source_type, sha256, size_bytes, mtime_ns,
                parser_name, parser_version, parser_config,
                chunker_name, chunker_version, chunker_config,
                normalisation_version, normalisation_config, index_status
            ) VALUES (?, 'markdown', ?, 123, 1, 'parser', '1', '{}', 'chunker', '1', '{}', '1', '{}', 'indexed')
            """,
            ("docs/a.md", "a" * 64),
        )
        source_pk = conn.execute("SELECT source_pk FROM sources").fetchone()[0]
        conn.execute(
            "INSERT INTO pages(source_pk, physical_page, text, extraction_method, extraction_status, layout_json) VALUES (?, 1, ?, 'text', 'ok', ?)",
            (source_pk, "page text body", '{"blocks":[1]}'),
        )
        conn.execute(
            """
            INSERT INTO chunks (
                chunk_id, source_pk, logical_key, ordinal, body,
                semantic_input_hash, lexical_hash, content_type
            ) VALUES ('c1', ?, 'p1', 1, ?, ?, ?, 'markdown')
            """,
            (source_pk, "chunk body text", "b" * 64, "c" * 64),
        )
        if vectors:
            conn.execute(
                "INSERT INTO embeddings(model_id, semantic_input_hash, created_at_utc) VALUES (?, ?, ?)",
                (schema.embedding_model_id(), "b" * 64, schema.utc_now()),
            )
            embedding_id = conn.execute("SELECT embedding_id FROM embeddings").fetchone()[0]
            conn.execute("INSERT INTO chunk_embeddings(chunk_id, embedding_id) VALUES ('c1', ?)", (embedding_id,))
            vector_backend.SqliteVecBackend().upsert(conn, embedding_id, [float(index) / 1000.0 for index in range(schema.EMBEDDING_DIMENSIONS)])
        conn.execute(
            "INSERT INTO assets(asset_id, source_pk, physical_page, asset_path, sha256, asset_type) VALUES ('asset1', ?, 1, 'imgs/generations/g/1/page.png', ?, 'page')",
            (source_pk, "d" * 64),
        )
        if bloat:
            conn.execute("CREATE TABLE transient_bloat(payload TEXT)")
            conn.executemany("INSERT INTO transient_bloat(payload) VALUES (?)", [("x" * 2048,) for _ in range(128)])
            conn.execute("DROP TABLE transient_bloat")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    return path


def bytes_of(path: Path) -> bytes:
    return path.read_bytes()


def test_diagnose_requires_existing_database_and_does_not_create(tmp_path: Path):
    diagnose = load_script("diagnose_database")
    missing = tmp_path / "missing" / "db.sqlite"
    with pytest.raises(SystemExit):
        diagnose.main([str(missing), "--json"])
    assert not missing.exists()
    assert not missing.parent.exists()


def test_diagnose_reports_allocation_math_hash_bytes_and_tables(tmp_path: Path, capsys):
    diagnose = load_script("diagnose_database")
    db = make_db(tmp_path / "tracecite.sqlite")
    report = diagnose.diagnose_database(db)
    assert report["file_bytes"] == db.stat().st_size
    assert report["freelist_bytes"] == report["page_size"] * report["freelist_pages"]
    assert report["used_bytes"] == report["page_size"] * (report["page_count"] - report["freelist_pages"])
    assert report["hash_storage_bytes"]["diagnostic_note"].startswith("Stored hashes are diagnostic")
    assert report["hash_storage_bytes"]["total_bytes"] >= 64 * 3
    assert report["text_storage_bytes"]["pages.text"] > 0
    assert report["text_storage_bytes"]["pages.layout_json"] > 0
    assert report["text_storage_bytes"]["chunks.body"] > 0
    assert report["row_counts"]["sources"] == 1
    assert report["dbstat_available"] in {True, False}
    diagnose.main([str(db), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["database"] == str(db)
    diagnose.main([str(db)])
    assert "Hash storage (diagnostic contribution, not raw source files)" in capsys.readouterr().out


def test_preview_compaction_leaves_bytes_unchanged(tmp_path: Path):
    compact = load_script("compact_database")
    db = make_db(tmp_path / "tracecite.sqlite", bloat=True)
    before = bytes_of(db)
    result = compact.compact_database(db, apply=False)
    assert result["applied"] is False
    assert bytes_of(db) == before


def test_successful_compaction_shrinks_and_preserves_logical_database(tmp_path: Path):
    compact = load_script("compact_database")
    db = make_db(tmp_path / "tracecite.sqlite", bloat=True)
    before_size = db.stat().st_size
    before_fingerprint = compact.logical_fingerprint(db)
    before_vectors = compact.vector_fingerprint(db)
    assert before_vectors["row_count"] == 1
    assert before_vectors["embedding_ids"] == [1]
    assert before_vectors["dimensions"] == 384
    assert before_vectors["digest"]
    result = compact.compact_database(db, apply=True)
    assert result["applied"] is True
    assert result["after"]["file_bytes"] < before_size
    assert result["reclaimed_bytes"] == before_size - result["after"]["file_bytes"]
    assert compact.logical_fingerprint(db) == before_fingerprint
    assert compact.vector_fingerprint(db) == before_vectors
    assert not list(tmp_path.glob("*.tracecite-compact-*"))
    assert not list(tmp_path.glob("*.tracecite-original-*"))
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_zero_vectors_are_validated_as_explicit_empty_payload(tmp_path: Path):
    compact = load_script("compact_database")
    db = make_db(tmp_path / "tracecite.sqlite", vectors=False)
    fingerprint = compact.vector_fingerprint(db)
    assert fingerprint == {
        "available": True,
        "row_count": 0,
        "embedding_ids": [],
        "dimensions": 384,
        "digest": hashlib.sha256(b"").hexdigest(),
    }
    assert compact.compact_database(db, apply=True)["applied"] is True
    assert compact.vector_fingerprint(db) == fingerprint


def test_vector_fingerprint_labels_unavailable_extension_as_failure(tmp_path: Path, monkeypatch):
    compact = load_script("compact_database")
    db = make_db(tmp_path / "tracecite.sqlite")
    from tracecite.evidence import schema

    def raw_connection(path, *, read_only):
        assert read_only is True
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(schema, "connect_existing", raw_connection)
    monkeypatch.setattr(schema, "ensure_schema", lambda conn: None)
    with pytest.raises(compact.MaintenanceError, match="sqlite-vec vector payload unavailable"):
        compact.vector_fingerprint(db)


def test_candidate_vector_corruption_fails_validation_and_preserves_original_bytes(tmp_path: Path):
    compact = load_script("compact_database")
    db = make_db(tmp_path / "tracecite.sqlite", bloat=True)
    original = bytes_of(db)
    hooks = compact.MaintenanceHooks(corrupt_candidate_vectors=True)
    with pytest.raises(compact.MaintenanceError, match="candidate vector payload differs from original"):
        compact.compact_database(db, apply=True, hooks=hooks)
    assert bytes_of(db) == original
    assert compact.vector_fingerprint(db)["row_count"] == 1


@pytest.mark.parametrize("sidecar", ["-wal", "-shm", "-journal"])
def test_compaction_refuses_sidecars(tmp_path: Path, sidecar: str):
    compact = load_script("compact_database")
    db = make_db(tmp_path / "tracecite.sqlite")
    db.with_name(db.name + sidecar).write_text("active", encoding="utf-8")
    with pytest.raises(compact.MaintenanceError, match="sidecar"):
        compact.compact_database(db, apply=True)


def test_compaction_refuses_missing_symlink_and_non_regular(tmp_path: Path):
    compact = load_script("compact_database")
    with pytest.raises(compact.MaintenanceError, match="does not exist"):
        compact.compact_database(tmp_path / "missing.sqlite", apply=True)
    db = make_db(tmp_path / "tracecite.sqlite")
    link = tmp_path / "link.sqlite"
    link.symlink_to(db)
    with pytest.raises(compact.MaintenanceError, match="symlink"):
        compact.compact_database(link, apply=True)
    directory = tmp_path / "dir.sqlite"
    directory.mkdir()
    with pytest.raises(compact.MaintenanceError, match="regular"):
        compact.compact_database(directory, apply=True)


@pytest.mark.parametrize(
    "fail_at, message, original_preserved",
    [
        ("candidate", "candidate creation failed", True),
        ("prevalidate", "validation failed", True),
        ("first_replace", "first replace failed", True),
        ("second_replace", "second replace failed", True),
        ("postvalidate", "validation failed", True),
        ("cleanup", "cleanup failed", False),
    ],
)
def test_compaction_failure_paths_preserve_or_restore_original(tmp_path: Path, fail_at: str, message: str, original_preserved: bool):
    compact = load_script("compact_database")
    db = make_db(tmp_path / "tracecite.sqlite", bloat=True)
    original = bytes_of(db)
    hooks = compact.MaintenanceHooks(fail_at=fail_at)
    with pytest.raises(compact.MaintenanceError, match=message):
        compact.compact_database(db, apply=True, hooks=hooks)
    if original_preserved:
        assert bytes_of(db) == original
    assert not any(path.name.endswith(".tracecite-compact-candidate") for path in tmp_path.iterdir())


def test_compaction_json_cli_reports_before_after(tmp_path: Path, capsys):
    compact = load_script("compact_database")
    db = make_db(tmp_path / "tracecite.sqlite", bloat=True)
    assert compact.main([str(db), "--apply", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    assert payload["before"]["file_bytes"] > payload["after"]["file_bytes"]
    assert payload["reclaimed_bytes"] > 0


def test_scripts_run_from_standalone_copied_core(tmp_path: Path):
    copied = tmp_path / "tracecite-core"
    # Generated documentation builds are outputs, not standalone package core.
    shutil.copytree(ROOT, copied, ignore=shutil.ignore_patterns("build"))
    db = make_db(tmp_path / "tracecite.sqlite")
    diagnose_path = copied / "scripts" / "diagnose_database.py"
    compact_path = copied / "scripts" / "compact_database.py"
    import subprocess

    diagnose = subprocess.run([sys.executable, diagnose_path, db, "--json"], check=True, text=True, capture_output=True)
    assert json.loads(diagnose.stdout)["file_bytes"] == db.stat().st_size
    before = db.read_bytes()
    preview = subprocess.run([sys.executable, compact_path, db, "--json"], check=True, text=True, capture_output=True)
    assert json.loads(preview.stdout)["applied"] is False
    assert db.read_bytes() == before
