"""Narrow vector-backend interface, hiding all sqlite-vec-specific SQL.

Synchronisation, retrieval, verification, and CLI code must depend only on
``SqliteVecBackend`` (or the ``VectorBackend`` protocol it implements), never
on vec0 virtual-table SQL directly. This is the seam plan 0006 requires so a
later vector-store migration would not require rewriting parsers, chunk
synchronisation, lexical retrieval, report verification, or the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence
import sqlite3

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


class VectorBackend(Protocol):
    def upsert(self, conn: sqlite3.Connection, embedding_id: int, vector: Sequence[float]) -> None: ...

    def delete(self, conn: sqlite3.Connection, embedding_id: int) -> None: ...

    def search(
        self,
        conn: sqlite3.Connection,
        query_vector: Sequence[float],
        top_k: int,
        allowed_embedding_ids: Sequence[int] | None = None,
    ) -> list[VectorMatch]: ...

    def integrity_check(self, conn: sqlite3.Connection) -> list[str]: ...

    def version(self, conn: sqlite3.Connection) -> str: ...

    def capabilities(self) -> dict[str, object]: ...


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
    """The default (and, for this task, only) vector-backend implementation."""

    def __init__(self, table: str = VECTOR_TABLE) -> None:
        self.table = table

    def upsert(self, conn: sqlite3.Connection, embedding_id: int, vector: Sequence[float]) -> None:
        packed = _sqlite_vec().serialize_float32(list(vector))
        conn.execute(f"DELETE FROM {self.table} WHERE embedding_id = ?", (embedding_id,))
        conn.execute(
            f"INSERT INTO {self.table}(embedding_id, shard_id, vector) VALUES (?, ?, ?)",
            (embedding_id, self._shard_id(embedding_id), packed),
        )

    def delete(self, conn: sqlite3.Connection, embedding_id: int) -> None:
        conn.execute(f"DELETE FROM {self.table} WHERE embedding_id = ?", (embedding_id,))

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
        if allowed_embedding_ids is not None:
            allowed = set(allowed_embedding_ids)
            if not allowed:
                return []
            matches = []
            for shard_id in {self._shard_id(embedding_id) for embedding_id in allowed}:
                shard_matches = self._knn(
                    conn, packed, shard_id, self._shard_row_count(conn, shard_id)
                )
                matches.extend(match for match in shard_matches if match.embedding_id in allowed)
            return sorted(matches, key=lambda match: match.distance)[:top_k]

        matches = []
        for shard_id in self._shard_ids(conn):
            shard_count = self._shard_row_count(conn, shard_id)
            matches.extend(self._knn(conn, packed, shard_id, min(top_k, shard_count)))
        return sorted(matches, key=lambda match: match.distance)[:top_k]

    @staticmethod
    def _shard_id(embedding_id: int) -> str:
        if embedding_id <= 0:
            raise ValueError("embedding_id must be positive")
        return str((embedding_id - 1) // MAX_KNN_K)

    def _shard_ids(self, conn: sqlite3.Connection) -> list[str]:
        rows = conn.execute(f"SELECT DISTINCT shard_id FROM {self.table}").fetchall()
        return [str(row[0]) for row in rows]

    def _shard_row_count(self, conn: sqlite3.Connection, shard_id: str) -> int:
        return int(
            conn.execute(
                f"SELECT count(*) FROM {self.table} WHERE shard_id = ?", (shard_id,)
            ).fetchone()[0]
        )

    def _knn(
        self,
        conn: sqlite3.Connection,
        packed_query: bytes,
        shard_id: str,
        k: int,
    ) -> list[VectorMatch]:
        if k <= 0:
            return []
        if k > MAX_KNN_K:
            raise ValueError(f"KNN k must not exceed {MAX_KNN_K}")
        rows = conn.execute(
            f"""
            SELECT embedding_id, distance FROM {self.table}
            WHERE vector MATCH ? AND shard_id = ? AND k = ?
            ORDER BY distance
            """,
            (packed_query, shard_id, k),
        ).fetchall()
        return [VectorMatch(embedding_id=row[0], distance=row[1]) for row in rows]

    def _row_count(self, conn: sqlite3.Connection) -> int:
        return int(conn.execute(f"SELECT count(*) FROM {self.table}").fetchone()[0])

    def integrity_check(self, conn: sqlite3.Connection) -> list[str]:
        issues: list[str] = []
        orphan_vectors = conn.execute(
            f"""
            SELECT v.embedding_id FROM {self.table} v
            LEFT JOIN embeddings e ON e.embedding_id = v.embedding_id
            WHERE e.embedding_id IS NULL
            """
        ).fetchall()
        for row in orphan_vectors:
            issues.append(f"vector row {row[0]} has no matching embeddings row")

        missing_vectors = conn.execute(
            f"""
            SELECT e.embedding_id FROM embeddings e
            LEFT JOIN {self.table} v ON v.embedding_id = e.embedding_id
            WHERE v.embedding_id IS NULL
            """
        ).fetchall()
        for row in missing_vectors:
            issues.append(f"embeddings row {row[0]} has no vector in {self.table}")

        vector_rows = self._row_count(conn)
        embedding_rows = int(conn.execute("SELECT count(*) FROM embeddings").fetchone()[0])
        if vector_rows != embedding_rows and not issues:
            issues.append(
                f"{self.table} has {vector_rows} rows but embeddings has {embedding_rows} rows"
            )
        return issues

    def version(self, conn: sqlite3.Connection) -> str:
        return version(conn)

    def capabilities(self) -> dict[str, object]:
        return {
            "backend": "sqlite-vec",
            "ann_index": False,
            "distance": "l2",
            "supports_bounded_filters": True,
        }
