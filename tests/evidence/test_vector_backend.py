"""Vector-backend contract tests (independent of vec0 SQL outside the
backend implementation) and sqlite-vec-specific behaviour checks."""

from __future__ import annotations

import sqlite3

import pytest

from tracecite.evidence import schema, vector_backend


@pytest.fixture
def conn(tmp_path):
    database_path = tmp_path / "vectors.sqlite"
    connection = schema.connect(database_path)
    schema.ensure_schema(connection)
    yield connection
    connection.close()


def _insert_embedding(conn: sqlite3.Connection, model_id: str, semantic_hash: str) -> int:
    cursor = conn.execute(
        "INSERT INTO embeddings(model_id, semantic_input_hash, created_at_utc) VALUES (?, ?, ?)",
        (model_id, semantic_hash, schema.utc_now()),
    )
    return cursor.lastrowid


def test_backend_reports_version_and_capabilities(conn):
    backend = vector_backend.SqliteVecBackend()
    assert backend.version(conn).startswith("v")
    caps = backend.capabilities()
    assert caps["ann_index"] is False
    assert caps["backend"] == "sqlite-vec"


def test_backend_upsert_search_delete_contract(conn):
    """Uses only the VectorBackend interface -- no vec0 SQL in this test."""

    backend: vector_backend.VectorBackend = vector_backend.SqliteVecBackend()
    dims = schema.EMBEDDING_DIMENSIONS

    id_a = _insert_embedding(conn, "model-x", "hash-a")
    id_b = _insert_embedding(conn, "model-x", "hash-b")

    vector_a = [1.0] + [0.0] * (dims - 1)
    vector_b = [0.0, 1.0] + [0.0] * (dims - 2)
    backend.upsert(conn, id_a, vector_a)
    backend.upsert(conn, id_b, vector_b)

    matches = backend.search(conn, vector_a, top_k=2)
    assert matches[0].embedding_id == id_a
    assert matches[0].distance == pytest.approx(0.0, abs=1e-4)

    filtered = backend.search(conn, vector_a, top_k=2, allowed_embedding_ids=[id_b])
    assert [m.embedding_id for m in filtered] == [id_b]

    backend.delete(conn, id_a)
    conn.execute("DELETE FROM chunk_embeddings WHERE embedding_id = ?", (id_a,))
    conn.execute("DELETE FROM embeddings WHERE embedding_id = ?", (id_a,))
    remaining = backend.search(conn, vector_a, top_k=2)
    assert [m.embedding_id for m in remaining] == [id_b]


def test_backend_integrity_check_detects_orphans(conn):
    backend = vector_backend.SqliteVecBackend()
    dims = schema.EMBEDDING_DIMENSIONS
    embedding_id = _insert_embedding(conn, "model-x", "hash-c")
    # Deliberately do not insert a vector row -- an orphaned embeddings row.
    issues = backend.integrity_check(conn)
    assert any(str(embedding_id) in issue for issue in issues)

    backend.upsert(conn, embedding_id, [0.1] * dims)
    assert backend.integrity_check(conn) == []


def test_sqlite_vec_extension_loads_and_reports_version(conn):
    # This one test intentionally exercises the sqlite-vec extension surface
    # directly, so a version regression in the pinned dependency is caught
    # even though the rest of the suite never touches vec0 SQL directly.
    version = vector_backend.version(conn)
    assert version.startswith("v0.")


def test_backend_search_scans_shards_for_filtered_and_unfiltered_results(conn):
    """A 4097-row corpus exercises the sqlite-vec per-query k limit."""

    backend = vector_backend.SqliteVecBackend()
    dims = schema.EMBEDDING_DIMENSIONS
    query = [0.0] * dims
    allowed_ids = []
    second_shard_id = None

    for index in range(4097):
        embedding_id = _insert_embedding(conn, "model-x", f"hash-{index}")
        if index == 0:
            value = 0.5
            allowed_ids.append(embedding_id)
        elif index == 4096:
            value = 0.1
            second_shard_id = embedding_id
            allowed_ids.append(embedding_id)
        else:
            value = 0.2
        backend.upsert(conn, embedding_id, [value] + [0.0] * (dims - 1))

    filtered = backend.search(conn, query, top_k=2, allowed_embedding_ids=allowed_ids)
    assert [match.embedding_id for match in filtered] == [second_shard_id, allowed_ids[0]]

    unfiltered = backend.search(conn, query, top_k=1)
    assert [match.embedding_id for match in unfiltered] == [second_shard_id]


def test_schema_v1_database_requires_rebuild_and_resync(tmp_path):
    """This is the closest existing test module for schema compatibility."""

    database_path = tmp_path / "schema-v1.sqlite"
    connection = schema.connect(database_path)
    schema.ensure_schema(connection)
    connection.execute("UPDATE kb_config SET schema_version = 1 WHERE id = 1")
    connection.close()

    connection = schema.connect(database_path)
    with pytest.raises(schema.IncompatibleDatabaseError, match="fresh.*database|re-sync"):
        schema.ensure_schema(connection)
    connection.close()
