#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid
from typing import Any


def _ensure_source_import() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


_ensure_source_import()

try:
    from diagnose_database import diagnose_database, format_human
except ModuleNotFoundError:
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    from diagnose_database import diagnose_database, format_human


class MaintenanceError(RuntimeError):
    pass


ORDINARY_TABLES = ("kb_config", "sources", "pages", "chunks", "embeddings", "chunk_embeddings", "assets")


@dataclass
class MaintenanceHooks:
    fail_at: str | None = None
    corrupt_candidate_vectors: bool = False

    def maybe_fail(self, point: str) -> None:
        if self.fail_at == point:
            messages = {
                "candidate": "candidate creation failed",
                "prevalidate": "validation failed before replacement",
                "first_replace": "first replace failed",
                "second_replace": "second replace failed",
                "postvalidate": "validation failed after replacement",
                "cleanup": "cleanup failed",
            }
            raise OSError(messages.get(point, f"injected failure at {point}"))

    def replace(self, src: Path, dst: Path, point: str) -> None:
        self.maybe_fail(point)
        os.replace(src, dst)

    def unlink(self, path: Path) -> None:
        self.maybe_fail("cleanup")
        Path(path).unlink()

    def after_candidate_created(self, candidate: Path) -> None:
        if not self.corrupt_candidate_vectors:
            return
        from tracecite.evidence import schema

        conn = schema.connect_existing(candidate, read_only=False)
        try:
            row = conn.execute("SELECT embedding_id FROM embedding_vectors ORDER BY embedding_id LIMIT 1").fetchone()
            if row is not None:
                conn.execute("DELETE FROM embedding_vectors WHERE embedding_id = ?", (row[0],))
        finally:
            conn.close()


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _connect_ro(path: Path) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _connect_rw_existing(path: Path) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=rw"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def table_row_counts(path: Path) -> dict[str, int | None]:
    with _connect_ro(path) as conn:
        counts: dict[str, int | None] = {}
        for table in ORDINARY_TABLES:
            counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}").fetchone()[0]) if _table_exists(conn, table) else None
        return counts


def kb_config_values(path: Path) -> list[dict[str, Any]]:
    with _connect_ro(path) as conn:
        if not _table_exists(conn, "kb_config"):
            return []
        return [dict(row) for row in conn.execute("SELECT * FROM kb_config ORDER BY id")]


def logical_fingerprint(path: Path) -> dict[str, str | None]:
    fingerprints: dict[str, str | None] = {}
    with _connect_ro(path) as conn:
        for table in ORDINARY_TABLES:
            if not _table_exists(conn, table):
                fingerprints[table] = None
                continue
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({_quote_identifier(table)})")]
            order = ", ".join(_quote_identifier(column) for column in columns)
            digest = hashlib.sha256()
            for row in conn.execute(f"SELECT * FROM {_quote_identifier(table)} ORDER BY {order}"):
                digest.update(json.dumps(dict(row), sort_keys=True, default=str, separators=(",", ":")).encode("utf-8"))
                digest.update(b"\n")
            fingerprints[table] = digest.hexdigest()
    return fingerprints


def vector_fingerprint(path: Path) -> dict[str, Any]:
    from tracecite.evidence import schema

    conn = schema.connect_existing(path, read_only=True)
    try:
        schema.ensure_schema(conn)
        digest = hashlib.sha256()
        embedding_ids: list[int] = []
        try:
            rows = conn.execute("SELECT embedding_id, vector FROM embedding_vectors ORDER BY embedding_id").fetchall()
        except sqlite3.Error as exc:
            raise MaintenanceError(f"sqlite-vec vector payload unavailable: {exc}") from exc
        for row in rows:
            embedding_id = int(row["embedding_id"])
            vector = bytes(row["vector"])
            embedding_ids.append(embedding_id)
            digest.update(str(embedding_id).encode("ascii"))
            digest.update(b"\0")
            digest.update(str(len(vector) // 4).encode("ascii"))
            digest.update(b"\0")
            digest.update(vector)
            digest.update(b"\n")
        return {
            "available": True,
            "row_count": len(rows),
            "embedding_ids": embedding_ids,
            "dimensions": schema.EMBEDDING_DIMENSIONS,
            "digest": digest.hexdigest(),
        }
    finally:
        conn.close()


def _quick_check(path: Path) -> None:
    with _connect_ro(path) as conn:
        result = conn.execute("PRAGMA quick_check").fetchone()[0]
    if result != "ok":
        raise MaintenanceError(f"quick_check failed for {path}: {result}")


def _tracecite_schema_check(path: Path) -> None:
    from tracecite.evidence import schema

    conn = schema.connect_existing(path, read_only=True)
    try:
        schema.ensure_schema(conn)
    finally:
        conn.close()


def validate_candidate(candidate: Path, original: Path, *, expected_counts: dict[str, int | None], expected_config: list[dict[str, Any]], expected_fingerprint: dict[str, str | None], expected_vectors: dict[str, Any]) -> None:
    _quick_check(candidate)
    _tracecite_schema_check(candidate)
    if table_row_counts(candidate) != expected_counts:
        raise MaintenanceError("candidate table row counts differ from original")
    if kb_config_values(candidate) != expected_config:
        raise MaintenanceError("candidate kb_config values differ from original")
    if logical_fingerprint(candidate) != expected_fingerprint:
        raise MaintenanceError("candidate logical fingerprints differ from original")
    if vector_fingerprint(candidate) != expected_vectors:
        raise MaintenanceError("candidate vector payload differs from original")


def _validate_target(path: Path) -> None:
    if not path.exists():
        raise MaintenanceError(f"database does not exist: {path}")
    if path.is_symlink():
        raise MaintenanceError(f"database must not be a symlink: {path}")
    if not path.is_file():
        raise MaintenanceError(f"database must be a regular file: {path}")
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = path.with_name(path.name + suffix)
        if sidecar.exists():
            raise MaintenanceError(f"refusing to compact while SQLite sidecar exists: {sidecar}")
    if path.stat().st_dev != path.parent.stat().st_dev:
        raise MaintenanceError("database and parent directory are not on same filesystem")


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_parent(path: Path) -> None:
    try:
        fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _vacuum_into(source: Path, candidate: Path, hooks: MaintenanceHooks) -> None:
    hooks.maybe_fail("candidate")
    with _connect_rw_existing(source) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM INTO ?", (str(candidate),))


def compact_database(database: Path, *, apply: bool = False, hooks: MaintenanceHooks | None = None) -> dict[str, Any]:
    hooks = hooks or MaintenanceHooks()
    database = Path(database)
    _validate_target(database)
    before = diagnose_database(database)
    if not apply:
        return {"database": str(database), "applied": False, "before": before, "after": before, "reclaimed_bytes": 0}

    mode = database.stat().st_mode & 0o7777
    expected_counts = table_row_counts(database)
    expected_config = kb_config_values(database)
    expected_fingerprint = logical_fingerprint(database)
    expected_vectors = vector_fingerprint(database)
    token = uuid.uuid4().hex
    candidate = database.with_name(f"{database.name}.tracecite-compact-{token}.candidate")
    quarantine = database.with_name(f"{database.name}.tracecite-original-{token}")
    installed_failed = database.with_name(f"{database.name}.tracecite-compact-{token}.failed-install")
    try:
        _vacuum_into(database, candidate, hooks)
        hooks.after_candidate_created(candidate)
        os.chmod(candidate, mode)
        _fsync_file(candidate)
        validate_candidate(candidate, database, expected_counts=expected_counts, expected_config=expected_config, expected_fingerprint=expected_fingerprint, expected_vectors=expected_vectors)
        hooks.maybe_fail("prevalidate")
        if candidate.stat().st_dev != database.parent.stat().st_dev:
            raise MaintenanceError("candidate is not on same filesystem as target")
        hooks.replace(database, quarantine, "first_replace")
        try:
            hooks.replace(candidate, database, "second_replace")
            try:
                validate_candidate(database, quarantine, expected_counts=expected_counts, expected_config=expected_config, expected_fingerprint=expected_fingerprint, expected_vectors=expected_vectors)
                hooks.maybe_fail("postvalidate")
            except Exception:
                if database.exists():
                    os.replace(database, installed_failed)
                os.replace(quarantine, database)
                raise
        except Exception:
            if not database.exists() and quarantine.exists():
                os.replace(quarantine, database)
            raise
        _fsync_parent(database)
        hooks.unlink(quarantine)
        after = diagnose_database(database)
        return {"database": str(database), "applied": True, "before": before, "after": after, "reclaimed_bytes": before["file_bytes"] - after["file_bytes"]}
    except MaintenanceError:
        raise
    except Exception as exc:
        raise MaintenanceError(str(exc)) from exc
    finally:
        for path in (candidate, installed_failed):
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass


def format_compaction(report: dict[str, Any]) -> str:
    lines = ["Before diagnostics:", format_human(report["before"]).rstrip(), "After diagnostics:", format_human(report["after"]).rstrip(), f"Applied: {report['applied']}", f"Reclaimed bytes: {report['reclaimed_bytes']}"]
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview or compact a TraceCite SQLite database safely.")
    parser.add_argument("database", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = compact_database(args.database, apply=args.apply)
    except MaintenanceError as exc:
        print(f"compact_database.py: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_compaction(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
