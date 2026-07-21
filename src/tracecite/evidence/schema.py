"""Versioned SQLite schema for the local TraceCite (plan 0006).

One SQLite file holds ordinary relational tables, an FTS5 lexical index, and
a normalised (model_id, semantic_input_hash)-keyed embedding store backed by
sqlite-vec. PDF page renders and crops are written to a repo-relative
``imgs/`` tree next to the database; SQLite stores only their metadata.

Every real corpus gets its own database created fresh with this schema from
the start (see task 0089's "Database-path model" contract). This module
does not migrate task 0083's bootstrap smoke-test table
(``tracecite_bootstrap``); it refuses to touch a database that already
contains unrecognised tables so a bootstrap artifact is never silently
reused as a real corpus database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import json
import re
import sqlite3

from . import vector_backend

SCHEMA_VERSION = 3

# Descriptive, not literal DDL -- recorded so a future FTS tokenizer/config
# change can be detected and trigger a documented "rebuild FTS only" step.
FTS_CONFIG = "fts5-unicode61-v1"

PARSER_NAME_PDF = "pdf-pymupdf"
PARSER_VERSION_PDF = "1"
PARSER_NAME_MARKDOWN = "markdown-heading"
PARSER_VERSION_MARKDOWN = "1"

CHUNKER_NAME = "greedy-char-budget"
CHUNKER_VERSION = "1"
DEFAULT_MAX_CHUNK_CHARS = 1200

NORMALISATION_VERSION = "1"

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
EMBEDDING_DIMENSIONS = 384


def embedding_model_id(model: str = EMBEDDING_MODEL, revision: str = EMBEDDING_REVISION) -> str:
    return f"{model}@{revision}"


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class KnowledgeBaseConfig:
    schema_version: int
    fts_config: str
    sqlite_vec_version: str
    embedding_model: str
    embedding_revision: str
    embedding_dimensions: int
    parser_versions: dict[str, str] = field(default_factory=dict)
    chunker_version: str = CHUNKER_VERSION
    normalisation_version: str = NORMALISATION_VERSION
    created_at_utc: str = ""
    updated_at_utc: str = ""

    @property
    def embedding_model_id(self) -> str:
        return embedding_model_id(self.embedding_model, self.embedding_revision)


_KNOWN_TABLES = {
    "kb_config",
    "sources",
    "pages",
    "chunks",
    "embeddings",
    "chunk_embeddings",
    "assets",
    "sqlite_sequence",
}
_KNOWN_TABLE_PREFIXES = ("chunks_fts", "embedding_vectors")

_REQUIRED_COLUMNS = {
    "kb_config": {
        "id",
        "schema_version",
        "fts_config",
        "sqlite_vec_version",
        "embedding_model",
        "embedding_revision",
        "embedding_dimensions",
        "parser_versions",
        "chunker_version",
        "normalisation_version",
        "created_at_utc",
        "updated_at_utc",
    },
    "sources": {"source_pk", "path", "source_type", "sha256", "size_bytes", "mtime_ns", "parser_name", "parser_version"},
    "pages": {"page_id", "source_pk", "physical_page", "text"},
    "chunks": {"chunk_id", "source_pk", "logical_key", "body", "semantic_input_hash"},
    "embeddings": {"embedding_id", "model_id", "semantic_input_hash"},
    "chunk_embeddings": {"chunk_id", "embedding_id"},
    "assets": {"asset_id", "source_pk", "asset_path", "sha256"},
}

_REQUIRED_OBJECTS = {
    "tables": {"kb_config", "sources", "pages", "chunks", "embeddings", "chunk_embeddings", "assets"},
    "virtual_tables": {"chunks_fts", "embedding_vectors"},
    "indexes": {"chunks_sourcepk_idx", "chunks_source_logical_idx", "chunks_semantic_hash_idx", "chunk_embeddings_embedding_idx", "assets_sourcepk_page_idx"},
    "triggers": {"chunks_ai", "chunks_ad", "chunks_au"},
}


def _is_known_table(name: str) -> bool:
    return name in _KNOWN_TABLES or name.startswith(_KNOWN_TABLE_PREFIXES)


class IncompatibleDatabaseError(RuntimeError):
    """Raised when a database path already holds data this tool did not create."""


def connect(database_path: Path) -> sqlite3.Connection:
    """Open a connection with sqlite-vec loaded and foreign keys enforced."""

    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    # True autocommit: every statement outside an explicit BEGIN commits
    # immediately, and nothing implicitly opens a transaction. sync.py relies
    # on this so its single explicit ``BEGIN IMMEDIATE`` block is the only
    # write transaction in the whole synchronisation lifecycle.
    conn = sqlite3.connect(database_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    vector_backend.ensure_loaded(conn)
    return conn


def connect_existing(database_path: Path, *, read_only: bool) -> sqlite3.Connection:
    """Open an existing database without creating parents, files, or schema."""

    database_path = Path(database_path)
    if not database_path.is_file():
        raise FileNotFoundError(f"database does not exist: {database_path}")
    mode = "ro" if read_only else "rw"
    uri = database_path.resolve().as_uri() + f"?mode={mode}"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    vector_backend.ensure_loaded(conn)
    return conn


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
    ).fetchall()
    return {row["name"] for row in rows}


def is_initialised(conn: sqlite3.Connection) -> bool:
    return "kb_config" in _existing_tables(conn)


def ensure_schema(conn: sqlite3.Connection) -> KnowledgeBaseConfig:
    """Create the schema if the database is empty, or load its config.

    Raises ``IncompatibleDatabaseError`` if the database already has tables
    that are not part of this schema (for example, task 0083's bootstrap
    ``tracecite_bootstrap`` metadata table) -- callers must choose a
    fresh database path for a real corpus rather than reusing that one.
    """

    existing = _existing_tables(conn)
    if "kb_config" in existing:
        _validate_schema_objects(conn)
        config = load_config(conn)
        if config.schema_version != SCHEMA_VERSION:
            raise IncompatibleDatabaseError(
                f"database schema version {config.schema_version} is incompatible; "
                f"expected version {SCHEMA_VERSION}. Select a fresh --database path "
                "and re-run sync to rebuild the database; automatic migration is "
                "not supported"
            )
        return config

    unknown = {name for name in existing if not _is_known_table(name)}
    if unknown:
        raise IncompatibleDatabaseError(
            "database already contains unrecognised tables "
            f"({sorted(unknown)}); this tool never migrates or reuses an "
            "unrelated database (e.g. task 0083's bootstrap smoke-test "
            "file) -- choose a fresh --database path for this corpus"
        )

    _create_schema(conn)
    _validate_schema_objects(conn)
    return load_config(conn)


def _object_names(conn: sqlite3.Connection, object_type: str) -> set[str]:
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (object_type,)).fetchall()
    }


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _validate_schema_objects(conn: sqlite3.Connection) -> None:
    tables = _object_names(conn, "table") | _object_names(conn, "view")
    for table in sorted(_REQUIRED_OBJECTS["tables"] | _REQUIRED_OBJECTS["virtual_tables"]):
        if table not in tables:
            raise IncompatibleDatabaseError(f"schema v{SCHEMA_VERSION} is missing required object {table}")
    indexes = _object_names(conn, "index")
    for index in sorted(_REQUIRED_OBJECTS["indexes"]):
        if index not in indexes:
            raise IncompatibleDatabaseError(f"schema v{SCHEMA_VERSION} is missing required index {index}")
    triggers = _object_names(conn, "trigger")
    for trigger in sorted(_REQUIRED_OBJECTS["triggers"]):
        if trigger not in triggers:
            raise IncompatibleDatabaseError(f"schema v{SCHEMA_VERSION} is missing required trigger {trigger}")
    for table, required_columns in sorted(_REQUIRED_COLUMNS.items()):
        columns = _columns(conn, table)
        missing = required_columns - columns
        if missing:
            for preferred in ("source_pk", "source_type", "embedding_model"):
                if preferred in missing:
                    raise IncompatibleDatabaseError(
                        f"schema v{SCHEMA_VERSION} table {table} is missing required column {preferred}"
                    )
            else:
                raise IncompatibleDatabaseError(
                    f"schema v{SCHEMA_VERSION} table {table} is missing required column {sorted(missing)[0]}"
                )
    if "assets" in tables and "asset_path" in _columns(conn, "assets"):
        absolute = conn.execute("SELECT asset_path FROM assets WHERE asset_path GLOB '/*' LIMIT 1").fetchone()
        if absolute is not None:
            raise IncompatibleDatabaseError("schema v3 database contains absolute asset paths and must be rebuilt")


def _create_schema(conn: sqlite3.Connection) -> None:
    sqlite_vec_version = vector_backend.version(conn)
    now = utc_now()
    parser_versions = {
        "pdf": f"{PARSER_NAME_PDF}@{PARSER_VERSION_PDF}",
        "markdown": f"{PARSER_NAME_MARKDOWN}@{PARSER_VERSION_MARKDOWN}",
    }

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            CREATE TABLE kb_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                schema_version INTEGER NOT NULL,
                fts_config TEXT NOT NULL,
                sqlite_vec_version TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                embedding_revision TEXT NOT NULL,
                embedding_dimensions INTEGER NOT NULL,
                parser_versions TEXT NOT NULL,
                chunker_version TEXT NOT NULL,
                normalisation_version TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO kb_config (
                id, schema_version, fts_config, sqlite_vec_version,
                embedding_model, embedding_revision, embedding_dimensions,
                parser_versions, chunker_version, normalisation_version,
                created_at_utc, updated_at_utc
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                SCHEMA_VERSION,
                FTS_CONFIG,
                sqlite_vec_version,
                EMBEDDING_MODEL,
                EMBEDDING_REVISION,
                EMBEDDING_DIMENSIONS,
                json.dumps(parser_versions, sort_keys=True),
                CHUNKER_VERSION,
                NORMALISATION_VERSION,
                now,
                now,
            ),
        )

        conn.execute(
            """
            CREATE TABLE sources (
                source_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                language TEXT,
                canonical_url TEXT,
                capture_manifest_ref TEXT,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                parser_name TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                parser_config TEXT NOT NULL,
                chunker_name TEXT NOT NULL,
                chunker_version TEXT NOT NULL,
                chunker_config TEXT NOT NULL,
                normalisation_version TEXT NOT NULL,
                normalisation_config TEXT NOT NULL,
                indexed_at_utc TEXT,
                index_status TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE pages (
                page_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_pk INTEGER NOT NULL REFERENCES sources(source_pk) ON DELETE CASCADE,
                physical_page INTEGER NOT NULL,
                printed_label TEXT,
                text TEXT NOT NULL,
                extraction_method TEXT NOT NULL,
                extraction_status TEXT NOT NULL,
                section_candidates TEXT,
                layout_json TEXT,
                UNIQUE(source_pk, physical_page)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                source_pk INTEGER NOT NULL REFERENCES sources(source_pk) ON DELETE CASCADE,
                logical_key TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                heading_path TEXT,
                symbol TEXT,
                body TEXT NOT NULL,
                semantic_input_hash TEXT NOT NULL,
                lexical_hash TEXT NOT NULL,
                content_type TEXT NOT NULL,
                physical_page INTEGER,
                page_start_offset INTEGER,
                page_end_offset INTEGER,
                page_range_start INTEGER,
                page_range_end INTEGER,
                line_start INTEGER,
                line_end INTEGER,
                locator_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX chunks_sourcepk_idx ON chunks(source_pk)")
        conn.execute(
            "CREATE INDEX chunks_source_logical_idx ON chunks(source_pk, logical_key)"
        )
        conn.execute(
            "CREATE INDEX chunks_semantic_hash_idx ON chunks(semantic_input_hash)"
        )

        conn.execute(
            """
            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                body,
                heading_path,
                symbol,
                content='chunks',
                content_rowid='rowid',
                tokenize='unicode61'
            )
            """
        )
        conn.execute(
            """
            CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, body, heading_path, symbol)
                VALUES (new.rowid, new.body, new.heading_path, new.symbol);
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, body, heading_path, symbol)
                VALUES ('delete', old.rowid, old.body, old.heading_path, old.symbol);
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, body, heading_path, symbol)
                VALUES ('delete', old.rowid, old.body, old.heading_path, old.symbol);
                INSERT INTO chunks_fts(rowid, body, heading_path, symbol)
                VALUES (new.rowid, new.body, new.heading_path, new.symbol);
            END
            """
        )

        conn.execute(
            """
            CREATE TABLE embeddings (
                embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id TEXT NOT NULL,
                semantic_input_hash TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                UNIQUE(model_id, semantic_input_hash)
            )
            """
        )
        conn.execute(
            f"""
            CREATE VIRTUAL TABLE embedding_vectors USING vec0(
                embedding_id INTEGER PRIMARY KEY,
                shard_id TEXT PARTITION KEY,
                vector FLOAT[{EMBEDDING_DIMENSIONS}]
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE chunk_embeddings (
                chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
                embedding_id INTEGER NOT NULL REFERENCES embeddings(embedding_id) ON DELETE CASCADE,
                PRIMARY KEY (chunk_id, embedding_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX chunk_embeddings_embedding_idx ON chunk_embeddings(embedding_id)"
        )

        conn.execute(
            """
            CREATE TABLE assets (
                asset_id TEXT PRIMARY KEY,
                source_pk INTEGER NOT NULL REFERENCES sources(source_pk) ON DELETE CASCADE,
                physical_page INTEGER NOT NULL,
                asset_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                width INTEGER,
                height INTEGER,
                asset_type TEXT NOT NULL,
                label TEXT,
                caption TEXT,
                nearby_text TEXT,
                ocr_text TEXT,
                visual_description TEXT,
                bbox_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX assets_sourcepk_page_idx ON assets(source_pk, physical_page)")
        conn.execute("COMMIT")
    except Exception:
        try:
            if getattr(conn, "in_transaction", True):
                conn.execute("ROLLBACK")
        except Exception:
            pass
        raise


def load_config(conn: sqlite3.Connection) -> KnowledgeBaseConfig:
    row = conn.execute("SELECT * FROM kb_config WHERE id = 1").fetchone()
    if row is None:
        raise IncompatibleDatabaseError("kb_config table exists but has no row")
    return KnowledgeBaseConfig(
        schema_version=row["schema_version"],
        fts_config=row["fts_config"],
        sqlite_vec_version=row["sqlite_vec_version"],
        embedding_model=row["embedding_model"],
        embedding_revision=row["embedding_revision"],
        embedding_dimensions=row["embedding_dimensions"],
        parser_versions=json.loads(row["parser_versions"]),
        chunker_version=row["chunker_version"],
        normalisation_version=row["normalisation_version"],
        created_at_utc=row["created_at_utc"],
        updated_at_utc=row["updated_at_utc"],
    )


def touch_config(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE kb_config SET updated_at_utc = ? WHERE id = 1", (utc_now(),))


def activate_embedding_config(
    conn: sqlite3.Connection,
    *,
    embedding_model: str,
    embedding_revision: str,
    embedding_dimensions: int,
) -> None:
    conn.execute(
        """
        UPDATE kb_config
        SET embedding_model = ?, embedding_revision = ?, embedding_dimensions = ?, updated_at_utc = ?
        WHERE id = 1
        """,
        (embedding_model, embedding_revision, embedding_dimensions, utc_now()),
    )


def imgs_dir(database_path: Path) -> Path:
    """The generated-assets tree, kept next to the database (outside SQLite)."""

    return Path(database_path).resolve().parent / "imgs"


def resolve_asset_path(database_path: Path, asset_identifier: str) -> Path:
    """Validate and resolve one stored asset identifier.

    The preferred identifier form is a POSIX path relative to the database
    parent beginning exactly with ``imgs/generations/``.  Existing databases may
    still contain absolute paths under that same tree until the storage
    migration runs.  The returned path is a validation snapshot: consumers must
    call this function again immediately before using it when an operation lock
    is held.
    """

    if not isinstance(asset_identifier, str) or not asset_identifier:
        raise ValueError("asset identifier must be a non-empty string")
    if "\x00" in asset_identifier or "\\" in asset_identifier:
        raise ValueError(f"asset identifier must be a POSIX path: {asset_identifier!r}")
    database_parent = Path(database_path).resolve().parent
    root = database_parent / "imgs"
    generations_root = root / "generations"
    root_resolved = root.resolve(strict=False)
    if root.is_symlink():
        raise ValueError(f"asset image root is a symlink: {root}")

    if asset_identifier.startswith("/"):
        candidate = Path(asset_identifier)
        try:
            candidate.relative_to(generations_root)
        except ValueError as exc:
            raise ValueError(f"asset path escapes image root: {asset_identifier!r}") from exc
    else:
        if re.match(r"^[A-Za-z]:", asset_identifier):
            raise ValueError(f"asset identifier must be relative: {asset_identifier!r}")

        parts = asset_identifier.split("/")
        if len(parts) < 3 or parts[:2] != ["imgs", "generations"]:
            raise ValueError(f"asset identifier has the wrong root: {asset_identifier!r}")
        if any(not part or part in (".", "..") for part in parts):
            raise ValueError(f"asset identifier is not normalized: {asset_identifier!r}")
        # Conversion happens only after the raw POSIX grammar has been checked.
        identifier = Path(*parts)
        candidate = database_parent.joinpath(*identifier.parts)

    current = database_parent
    for component in candidate.relative_to(database_parent).parts:
        current /= component
        if current.is_symlink():
            raise ValueError(f"asset path contains a symlink: {current}")

    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"asset path escapes image root: {asset_identifier!r}") from exc
    return candidate
