from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tracecite.evidence import schema


def test_schema_v3_uses_internal_source_pk_only(database_path: Path):
    with closing(schema.connect(database_path)) as conn:
        schema.ensure_schema(conn)
        columns = {
            table: [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
            for table in ("sources", "pages", "chunks", "assets")
        }
        assert columns["sources"][:2] == ["source_pk", "path"]
        for table in ("pages", "chunks", "assets"):
            assert "source_pk" in columns[table]
        source_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='sources'"
        ).fetchone()[0]
        assert "source_pk INTEGER PRIMARY KEY AUTOINCREMENT" in source_sql
        assert "path TEXT NOT NULL UNIQUE" in source_sql


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
    with closing(schema.connect(database_path)) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="injected vec0"):
            schema.ensure_schema(_FailingVecConnection(conn))
        assert _tracecite_objects(conn) == []
        schema.ensure_schema(conn)
        assert "embedding_vectors" in _tracecite_objects(conn)
        assert (
            conn.execute("SELECT schema_version FROM kb_config").fetchone()[0]
            == schema.SCHEMA_VERSION
        )


def _replace_sources_without_source_pk(conn):
    conn.execute("CREATE TABLE bad_sources AS SELECT path FROM sources")
    conn.execute("ALTER TABLE sources RENAME TO sources_real")
    conn.execute("ALTER TABLE bad_sources RENAME TO sources")


def _replace_table_with_columns(conn, table: str, columns: list[str]) -> None:
    conn.execute(
        f"CREATE TABLE bad_{table} AS SELECT {', '.join(columns)} FROM {table}"
    )
    conn.execute(f"ALTER TABLE {table} RENAME TO {table}_real")
    conn.execute(f"ALTER TABLE bad_{table} RENAME TO {table}")


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda conn: conn.execute("DROP TABLE chunks_fts"), "chunks_fts"),
        (
            lambda conn: conn.execute("DROP INDEX chunks_sourcepk_idx"),
            "chunks_sourcepk_idx",
        ),
        (lambda conn: conn.execute("DROP TRIGGER chunks_ai"), "chunks_ai"),
        (_replace_sources_without_source_pk, "source_pk"),
    ],
)
def test_ensure_schema_rejects_incomplete_matching_version_schema(
    database_path: Path, mutator, message
):
    with closing(schema.connect(database_path)) as conn:
        schema.ensure_schema(conn)
        mutator(conn)
        with pytest.raises(schema.IncompatibleDatabaseError, match=message):
            schema.ensure_schema(conn)


@pytest.mark.parametrize(
    "table, kept_columns, missing",
    [
        (
            "kb_config",
            ["id", "schema_version", "fts_config", "sqlite_vec_version"],
            "embedding_model",
        ),
        (
            "sources",
            ["source_pk", "path", "sha256", "size_bytes", "mtime_ns"],
            "source_type",
        ),
        (
            "chunks",
            ["chunk_id", "source_pk", "body", "semantic_input_hash"],
            "logical_key",
        ),
        ("assets", ["asset_id", "source_pk", "asset_path"], "sha256"),
    ],
)
def test_ensure_schema_rejects_missing_operational_columns(
    database_path: Path, table, kept_columns, missing
):
    with closing(schema.connect(database_path)) as conn:
        schema.ensure_schema(conn)
        _replace_table_with_columns(conn, table, kept_columns)
        with pytest.raises(schema.IncompatibleDatabaseError, match=missing):
            schema.ensure_schema(conn)
