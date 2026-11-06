from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

import pytest

from tracecite.evidence import schema


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
        with pytest.raises(sqlite3.DatabaseError):
            schema.ensure_schema(cast(sqlite3.Connection, _FailingVecConnection(conn)))
        assert _tracecite_objects(conn) == []
        schema.ensure_schema(conn)
        assert "embedding_vectors" in _tracecite_objects(conn)
        assert (
            conn.execute("SELECT schema_version FROM kb_config").fetchone()[0]
            == schema.SCHEMA_VERSION
        )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda conn: conn.execute("DROP TABLE chunks_fts"),
        lambda conn: conn.execute("DROP INDEX chunks_sourcepk_idx"),
        lambda conn: conn.execute("DROP TRIGGER chunks_ai"),
    ],
)
def test_ensure_schema_rejects_incomplete_matching_version_schema(
    database_path: Path, mutator
):
    with closing(schema.connect(database_path)) as conn:
        schema.ensure_schema(conn)
        mutator(conn)
        with pytest.raises(schema.IncompatibleDatabaseError):
            schema.ensure_schema(conn)
