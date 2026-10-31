"""sqlite-vec storage and KNN search for embedding vectors.

All vec0 virtual-table SQL lives here; the rest of the evidence code calls
``SqliteVecBackend``.
"""

from __future__ import annotations

import heapq
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

VECTOR_TABLE = "embedding_vectors"
MAX_KNN_K = 4096


def _sqlite_vec():
    try:
        import sqlite_vec
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "sqlite-vec is required for TraceCite evidence vector operations; "
            "install with tracecite[evidence]",
            name="sqlite_vec",
        ) from exc
    return sqlite_vec


@dataclass(frozen=True)
class VectorMatch:
    embedding_id: int
    distance: float


def ensure_loaded(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension into an open connection.

    Idempotent: safe to call on every ``connect()``, including connections
    made before the schema (and thus the vec0 virtual table) exists.
    """

    conn.enable_load_extension(True)
    try:
        _sqlite_vec().load(conn)
    finally:
        conn.enable_load_extension(False)


def version(conn: sqlite3.Connection) -> str:
    return str(conn.execute("SELECT vec_version()").fetchone()[0])


class SqliteVecBackend:
    def upsert(
        self, conn: sqlite3.Connection, embedding_id: int, vector: Sequence[float]
    ) -> None:
        packed = _sqlite_vec().serialize_float32(list(vector))
        self.delete(conn, embedding_id)
        conn.execute(
            f"INSERT INTO {VECTOR_TABLE}(embedding_id, shard_id, vector) VALUES (?, ?, ?)",
            (embedding_id, self._shard_id(embedding_id), packed),
        )

    def delete(self, conn: sqlite3.Connection, embedding_id: int) -> None:
        conn.execute(
            f"DELETE FROM {VECTOR_TABLE} WHERE embedding_id = ?", (embedding_id,)
        )

    def search(
        self,
        conn: sqlite3.Connection,
        query_vector: Sequence[float],
        top_k: int,
        allowed_embedding_ids: Sequence[int] | None = None,
    ) -> list[VectorMatch]:
        if top_k <= 0:
            return []
        packed = _sqlite_vec().serialize_float32(list(query_vector))
        shards: dict[str, list[int] | None] = {}
        if allowed_embedding_ids is None:
            rows = conn.execute(f"SELECT DISTINCT shard_id FROM {VECTOR_TABLE}")
            shards = dict.fromkeys(row[0] for row in rows)
        else:
            for embedding_id in set(allowed_embedding_ids):
                shards.setdefault(self._shard_id(embedding_id), []).append(embedding_id)

        matches = []
        for shard_id, allowed in shards.items():
            # A shard holds at most MAX_KNN_K rows, sqlite-vec's per-query k limit.
            sql = f"SELECT embedding_id, distance FROM {VECTOR_TABLE} WHERE vector MATCH ? AND shard_id = ? AND k = ?"
            parameters = [packed, shard_id, min(top_k, MAX_KNN_K)]
            if allowed is not None:
                # Filter before ranking, without one SQL parameter per allowed ID.
                sql += " AND embedding_id IN (SELECT value FROM json_each(?))"
                parameters.append(json.dumps(allowed))
            matches.extend(VectorMatch(*row) for row in conn.execute(sql, parameters))
        return heapq.nsmallest(top_k, matches, key=lambda match: match.distance)

    @staticmethod
    def _shard_id(embedding_id: int) -> str:
        if embedding_id <= 0:
            raise ValueError("embedding_id must be positive")
        return str((embedding_id - 1) // MAX_KNN_K)

    def integrity_check(self, conn: sqlite3.Connection) -> list[str]:
        orphan_vectors = conn.execute(
            f"""
            SELECT v.embedding_id FROM {VECTOR_TABLE} v
            LEFT JOIN embeddings e ON e.embedding_id = v.embedding_id
            WHERE e.embedding_id IS NULL
            """
        )
        issues = [
            f"vector row {row[0]} has no matching embeddings row"
            for row in orphan_vectors
        ]
        missing_vectors = conn.execute(
            f"""
            SELECT e.embedding_id FROM embeddings e
            LEFT JOIN {VECTOR_TABLE} v ON v.embedding_id = e.embedding_id
            WHERE v.embedding_id IS NULL
            """
        )
        issues += [
            f"embeddings row {row[0]} has no vector in {VECTOR_TABLE}"
            for row in missing_vectors
        ]
        return issues
