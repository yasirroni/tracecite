#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


def _ensure_source_import() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


_ensure_source_import()


class MaintenanceError(RuntimeError):
    pass


TEXT_COLUMNS = (
    ("pages", "text"),
    ("pages", "layout_json"),
    ("chunks", "body"),
)
HASH_COLUMNS = (
    ("sources", "sha256"),
    ("chunks", "semantic_input_hash"),
    ("chunks", "lexical_hash"),
    ("assets", "sha256"),
)
ROW_COUNT_TABLES = ("kb_config", "sources", "pages", "chunks", "embeddings", "chunk_embeddings", "assets")


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def connect_read_only(database: Path) -> sqlite3.Connection:
    database = Path(database)
    if not database.is_file():
        raise MaintenanceError(f"database does not exist: {database}")
    uri = database.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}


def _sum_lengths(conn: sqlite3.Connection, table: str, column: str, tables: set[str]) -> int | None:
    if table not in tables:
        return None
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({_quote_identifier(table)})")}
    if column not in cols:
        return None
    value = conn.execute(f"SELECT COALESCE(SUM(length({_quote_identifier(column)})), 0) FROM {_quote_identifier(table)}").fetchone()[0]
    return int(value or 0)


def _dbstat(conn: sqlite3.Connection) -> tuple[bool, list[dict[str, Any]], str | None]:
    try:
        rows = conn.execute(
            "SELECT name, SUM(pgsize) AS bytes, COUNT(*) AS pages FROM dbstat GROUP BY name ORDER BY bytes DESC, name"
        ).fetchall()
    except sqlite3.Error as exc:
        return False, [], str(exc)
    return True, [{"name": row[0], "bytes": int(row[1] or 0), "pages": int(row[2] or 0)} for row in rows], None


def diagnose_database(database: Path) -> dict[str, Any]:
    database = Path(database)
    with connect_read_only(database) as conn:
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
        freelist_pages = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
        tables = _tables(conn)
        row_counts: dict[str, int | str] = {}
        for table in ROW_COUNT_TABLES:
            if table not in tables:
                row_counts[table] = "unavailable: table not present"
            else:
                row_counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}").fetchone()[0])
        text_storage = {
            f"{table}.{column}": value if value is not None else "unavailable: table/column not present"
            for table, column in TEXT_COLUMNS
            for value in [_sum_lengths(conn, table, column, tables)]
        }
        hash_by_column = {
            f"{table}.{column}": value if value is not None else "unavailable: table/column not present"
            for table, column in HASH_COLUMNS
            for value in [_sum_lengths(conn, table, column, tables)]
        }
        hash_total = sum(value for value in hash_by_column.values() if isinstance(value, int))
        dbstat_available, dbstat_objects, dbstat_error = _dbstat(conn)
    used_bytes = page_size * (page_count - freelist_pages)
    freelist_bytes = page_size * freelist_pages
    file_bytes = database.stat().st_size
    return {
        "database": str(database),
        "file_bytes": file_bytes,
        "page_size": page_size,
        "page_count": page_count,
        "freelist_pages": freelist_pages,
        "freelist_bytes": freelist_bytes,
        "used_bytes": used_bytes,
        "reclaimable_percent": round((freelist_bytes / file_bytes * 100.0) if file_bytes else 0.0, 3),
        "dbstat_available": dbstat_available,
        "dbstat_error": dbstat_error,
        "dbstat_objects": dbstat_objects,
        "hash_storage_bytes": {
            "total_bytes": hash_total,
            "by_column": hash_by_column,
            "diagnostic_note": "Stored hashes are diagnostic metadata contribution, not raw source or asset file bytes.",
        },
        "text_storage_bytes": text_storage,
        "row_counts": row_counts,
    }


def format_human(report: dict[str, Any]) -> str:
    lines = [
        f"Database: {report['database']}",
        f"File bytes: {report['file_bytes']}",
        f"Page size/count: {report['page_size']} / {report['page_count']}",
        f"Freelist pages/bytes: {report['freelist_pages']} / {report['freelist_bytes']}",
        f"Used bytes: {report['used_bytes']}",
        f"Reclaimable percent: {report['reclaimable_percent']:.3f}%",
        "Per-object allocation (dbstat):",
    ]
    if report["dbstat_available"]:
        for item in report["dbstat_objects"]:
            lines.append(f"  {item['name']}: {item['bytes']} bytes ({item['pages']} pages)")
    else:
        lines.append(f"  unavailable: {report['dbstat_error']}")
    lines.append("Hash storage (diagnostic contribution, not raw source files):")
    lines.append(f"  total: {report['hash_storage_bytes']['total_bytes']} bytes")
    for name, value in report["hash_storage_bytes"]["by_column"].items():
        lines.append(f"  {name}: {value}")
    lines.append("Text/layout/chunk storage:")
    for name, value in report["text_storage_bytes"].items():
        lines.append(f"  {name}: {value}")
    lines.append("Row counts:")
    for name, value in report["row_counts"].items():
        lines.append(f"  {name}: {value}")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose TraceCite SQLite database allocation without modifying it.")
    parser.add_argument("database", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = diagnose_database(args.database)
    except MaintenanceError as exc:
        print(f"diagnose_database.py: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_human(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
