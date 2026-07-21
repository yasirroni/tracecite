from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from tracecite.evidence import schema, sync as sync_module

from conftest import build_pdf, write_manifest


def test_schema_v3_uses_internal_source_pk_only(database_path: Path):
    conn = schema.connect(database_path)
    try:
        schema.ensure_schema(conn)
        columns = {
            table: [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
            for table in ("sources", "pages", "chunks", "assets")
        }
        assert columns["sources"][:2] == ["source_pk", "path"]
        assert "source_id" not in columns["sources"]
        for table in ("pages", "chunks", "assets"):
            assert "source_pk" in columns[table]
            assert "source_id" not in columns[table]
        source_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='sources'").fetchone()[0]
        assert "source_pk INTEGER PRIMARY KEY AUTOINCREMENT" in source_sql
        assert "path TEXT NOT NULL UNIQUE" in source_sql
    finally:
        conn.close()


def test_search_and_tables_expose_paths_not_source_ids(corpus_dir, manifest_path, database_path, make_embedder):
    build_pdf(corpus_dir / "doc.pdf", [["Title", "Path identity should be the only public identity."]])
    write_manifest(manifest_path, {"doc.pdf": "doc.pdf"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    conn = schema.connect(database_path)
    try:
        source = conn.execute("SELECT * FROM sources").fetchone()
        assert source["path"] == "doc.pdf"
        assert "source_id" not in source.keys()
    finally:
        conn.close()


def _tracecite_objects(conn):
    return [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view', 'index', 'trigger') AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]


class _FailingVecConnection:
    def __init__(self, inner):
        self.inner = inner

    def execute(self, sql, *args, **kwargs):
        if "CREATE VIRTUAL TABLE embedding_vectors" in str(sql):
            raise sqlite3.DatabaseError("injected vec0 creation failure")
        return self.inner.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def __enter__(self):
        self.inner.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self.inner.__exit__(exc_type, exc, tb)


def test_schema_creation_rolls_back_partial_ddl_after_vec0_failure(database_path: Path):
    conn = schema.connect(database_path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="injected vec0"):
            schema.ensure_schema(_FailingVecConnection(conn))
        assert _tracecite_objects(conn) == []
        schema.ensure_schema(conn)
        assert "embedding_vectors" in _tracecite_objects(conn)
        assert conn.execute("SELECT schema_version FROM kb_config").fetchone()[0] == schema.SCHEMA_VERSION
    finally:
        conn.close()


def _replace_sources_without_source_pk(conn):
    conn.execute("CREATE TABLE bad_sources AS SELECT path FROM sources")
    conn.execute("ALTER TABLE sources RENAME TO sources_real")
    conn.execute("ALTER TABLE bad_sources RENAME TO sources")


def _replace_table_with_columns(conn, table: str, columns: list[str]) -> None:
    conn.execute(f"CREATE TABLE bad_{table} AS SELECT {', '.join(columns)} FROM {table}")
    conn.execute(f"ALTER TABLE {table} RENAME TO {table}_real")
    conn.execute(f"ALTER TABLE bad_{table} RENAME TO {table}")


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda conn: conn.execute("DROP TABLE chunks_fts"), "chunks_fts"),
        (lambda conn: conn.execute("DROP INDEX chunks_sourcepk_idx"), "chunks_sourcepk_idx"),
        (lambda conn: conn.execute("DROP TRIGGER chunks_ai"), "chunks_ai"),
        (_replace_sources_without_source_pk, "source_pk"),
    ],
)
def test_ensure_schema_rejects_incomplete_matching_version_schema(database_path: Path, mutator, message):
    conn = schema.connect(database_path)
    try:
        schema.ensure_schema(conn)
        mutator(conn)
        with pytest.raises(schema.IncompatibleDatabaseError, match=message):
            schema.ensure_schema(conn)
    finally:
        conn.close()


@pytest.mark.parametrize(
    "table, kept_columns, missing",
    [
        ("kb_config", ["id", "schema_version", "fts_config", "sqlite_vec_version"], "embedding_model"),
        ("sources", ["source_pk", "path", "sha256", "size_bytes", "mtime_ns"], "source_type"),
        ("chunks", ["chunk_id", "source_pk", "body", "semantic_input_hash"], "logical_key"),
        ("assets", ["asset_id", "source_pk", "asset_path"], "sha256"),
    ],
)
def test_ensure_schema_rejects_missing_operational_columns(database_path: Path, table, kept_columns, missing):
    conn = schema.connect(database_path)
    try:
        schema.ensure_schema(conn)
        _replace_table_with_columns(conn, table, kept_columns)
        with pytest.raises(schema.IncompatibleDatabaseError, match=missing):
            schema.ensure_schema(conn)
    finally:
        conn.close()
