"""Incremental, transaction-safe synchronisation lifecycle.

    scan filesystem
        |
    hash each selected file
        |
    parse only genuinely changed or invalidated files
        |
    compare old and new chunks
        |
    reuse or generate only missing embeddings
        |
    apply one SQLite transaction, rechecking source state before commit

Embeddings are generated before ``BEGIN IMMEDIATE``. If embedding fails, the
exception propagates before any write happens, so the database is left
unchanged. If a source's file changes between its first hash and the recheck
before commit, the transaction rolls back and the sync returns status
``"aborted-source-changed"`` so callers can retry.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import uuid
from collections import defaultdict, deque
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import chunking, schema, vector_backend
from . import manifest as manifest_module
from .embedding import Embedder, EmbeddingModel
from .parsers import markdown as markdown_parser
from .parsers import pdf as pdf_parser
from .parsers import workbook as workbook_parser
from .parsers.base import ParsedChunkUnit, units_from_layout
from .paths import file_sha256


class SyncError(RuntimeError):
    """A sync precondition failed (bad manifest, unmapped file, etc.)."""


class _SourceChangedDuringSync(RuntimeError):
    """A source no longer matches the snapshot used to build the transaction."""


@dataclass
class SyncOptions:
    max_chunk_chars: int = chunking.DEFAULT_MAX_CHUNK_CHARS
    generate_assets: bool = True
    cleanup_asset_generations: bool = True
    full: bool = False
    reembed: bool = False


def _parser(source_type: str) -> tuple:
    """Return the parser module, name, version, and config for a source type."""
    return {
        "pdf": (
            pdf_parser,
            schema.PARSER_NAME_PDF,
            schema.PARSER_VERSION_PDF,
            {"ocr_lang": pdf_parser.DEFAULT_OCR_LANG},
        ),
        "markdown": (
            markdown_parser,
            schema.PARSER_NAME_MARKDOWN,
            schema.PARSER_VERSION_MARKDOWN,
            {},
        ),
        "workbook": (
            workbook_parser,
            schema.PARSER_NAME_WORKBOOK,
            schema.PARSER_VERSION_WORKBOOK,
            {},
        ),
    }[source_type]


@dataclass
class SyncReport:
    status: str = "ok"
    sources_added: list[str] = field(default_factory=list)
    sources_reparsed: list[str] = field(default_factory=list)
    sources_rechunked: list[str] = field(default_factory=list)
    sources_unchanged: list[str] = field(default_factory=list)
    sources_renamed: list[tuple[str, str]] = field(default_factory=list)
    selected_missing_paths: list[str] = field(default_factory=list)
    missing_explicit_paths: list[str] = field(default_factory=list)
    # Selected sources this run did not index, with the reason. A source
    # indexed earlier keeps its previous rows.
    skipped_sources: dict[str, str] = field(default_factory=dict)
    # PDF physical pages with no extracted text, keyed by source path.
    pages_without_text: dict[str, list[int]] = field(default_factory=dict)
    indexed_unselected_paths: list[str] = field(default_factory=list)
    unmatched_globs: list[str] = field(default_factory=list)
    cleanup_warnings: list[str] = field(default_factory=list)
    chunks_added: int = 0
    chunks_updated: int = 0
    chunks_deleted: int = 0
    embeddings_generated: int = 0


def load_manifest_rules(
    manifest_paths: Path | Sequence[Path],
) -> manifest_module.ManifestRules:
    if isinstance(manifest_paths, (str, os.PathLike)):
        return manifest_module.merge_manifests([Path(manifest_paths)])
    return manifest_module.merge_manifests(list(manifest_paths))


def _identity(state: os.stat_result) -> tuple[int, int, int, int]:
    return state.st_dev, state.st_ino, state.st_size, state.st_mtime_ns


def _capture_stable_file_state(path: Path) -> tuple[str, int, int] | None:
    """Hash one stable, non-symlink file identity.

    The descriptor identity and the path identity must still agree after the
    read.  This catches path replacement as well as ordinary in-place writes.
    """

    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        before = os.fstat(descriptor)
        digest = hashlib.sha256()
        while block := os.read(descriptor, 1 << 20):
            digest.update(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    if (
        stat.S_ISLNK(current.st_mode)
        or _identity(before) != _identity(after)
        or _identity(current) != _identity(after)
    ):
        return None
    return digest.hexdigest(), after.st_size, after.st_mtime_ns


def _capture_source_snapshot(
    path: Path, snapshot_root: Path
) -> tuple[Path, tuple[str, int, int]] | None:
    """Copy one source into an immutable per-sync parsing snapshot, and return
    the copy's path with the file state it was copied from.

    A write during the copy leaves a hash the file no longer has, so the
    recheck before commit aborts the sync.
    """

    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    snapshot_path = snapshot_root / f"{uuid.uuid4().hex}{Path(path).suffix.lower()}"
    try:
        digest = hashlib.sha256()
        with snapshot_path.open("xb") as output:
            while block := os.read(descriptor, 1 << 20):
                digest.update(block)
                output.write(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    return snapshot_path, (digest.hexdigest(), after.st_size, after.st_mtime_ns)


def _observed_sources_match(
    observed_states: dict[str, tuple[Path, str, int, int]],
) -> bool:
    return all(
        _capture_stable_file_state(path) == tuple(expected)
        for path, *expected in observed_states.values()
    )


@dataclass
class _SourcePlan:
    source_path: str
    source_pk: int | None
    abs_path: Path
    source_type: str
    action: str  # "add" | "reparse" | "rechunk"
    file_state: tuple[str, int, int]  # (sha256, size_bytes, mtime_ns)
    snapshot_path: Path | None = None
    units: list[ParsedChunkUnit] = field(default_factory=list)
    pages: list = field(default_factory=list)
    # The chunk diff: (existing row, candidate) pairs, the chunk ids to
    # delete, and the candidates to insert.
    matched: list = field(default_factory=list)
    deleted_chunk_ids: list[str] = field(default_factory=list)
    new_candidates: list[chunking.ChunkCandidate] = field(default_factory=list)

    @property
    def content_path(self) -> Path:
        return self.snapshot_path or self.abs_path


def _source_error(exc: Exception, plan: _SourcePlan) -> str:
    """Describe a parser failure with the source path instead of its snapshot copy."""
    return (str(exc) or type(exc).__name__).replace(
        str(plan.content_path), plan.source_path
    )


def _match_chunks(
    existing_rows: list[sqlite3.Row], candidates: list[chunking.ChunkCandidate]
):
    """Match candidates to existing chunks by logical key, then by a semantic hash
    unique on both sides; the remaining candidates are new and the remaining
    rows are deleted.
    """

    existing_by_key: dict[str, deque[sqlite3.Row]] = defaultdict(deque)
    for row in existing_rows:
        existing_by_key[row["logical_key"]].append(row)

    matched: list[tuple[sqlite3.Row, chunking.ChunkCandidate]] = []
    used_existing_ids: set[str] = set()
    remaining_candidates: list[chunking.ChunkCandidate] = []

    for candidate in candidates:
        bucket = existing_by_key[candidate.logical_key]
        if bucket:
            row = bucket.popleft()
            used_existing_ids.add(row["chunk_id"])
            matched.append((row, candidate))
        else:
            remaining_candidates.append(candidate)

    remaining_existing = [
        row for row in existing_rows if row["chunk_id"] not in used_existing_ids
    ]

    hash_to_existing: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in remaining_existing:
        hash_to_existing[row["semantic_input_hash"]].append(row)
    hash_to_candidates: dict[str, list[chunking.ChunkCandidate]] = defaultdict(list)
    for candidate in remaining_candidates:
        hash_to_candidates[candidate.semantic_input_hash].append(candidate)

    consumed_candidate_ids: set[int] = set()
    still_remaining_existing: list[sqlite3.Row] = []
    for row in remaining_existing:
        hash_value = row["semantic_input_hash"]
        existing_bucket = hash_to_existing[hash_value]
        candidate_bucket = hash_to_candidates.get(hash_value, [])
        if len(existing_bucket) == 1 and len(candidate_bucket) == 1:
            candidate = candidate_bucket[0]
            matched.append((row, candidate))
            consumed_candidate_ids.add(id(candidate))
        else:
            still_remaining_existing.append(row)

    new_candidates = [
        c for c in remaining_candidates if id(c) not in consumed_candidate_ids
    ]
    to_delete_chunk_ids = [row["chunk_id"] for row in still_remaining_existing]
    return matched, to_delete_chunk_ids, new_candidates


def _config_matches(row: sqlite3.Row, options: SyncOptions, source_type: str) -> bool:
    return (
        (row["parser_name"], row["parser_version"]) == _parser(source_type)[1:3]
        and row["chunker_version"] == schema.CHUNKER_VERSION
        and row["normalisation_version"] == schema.NORMALISATION_VERSION
        and json.loads(row["chunker_config"]).get("max_chunk_chars")
        == options.max_chunk_chars
    )


def _needs_new_embedding(row: sqlite3.Row, candidate, options: SyncOptions) -> bool:
    return (
        options.reembed or row["semantic_input_hash"] != candidate.semantic_input_hash
    )


def _chunks_missing_active_embedding(
    conn: sqlite3.Connection, source_pk: int, model_id: str
):
    return conn.execute(
        """
        SELECT c.chunk_id AS chunk_id, c.semantic_input_hash AS semantic_input_hash, c.body AS body
        FROM chunks c
        WHERE c.source_pk = ?
        AND NOT EXISTS (
            SELECT 1 FROM chunk_embeddings ce
            JOIN embeddings e ON e.embedding_id = ce.embedding_id
            WHERE ce.chunk_id = c.chunk_id AND e.model_id = ?
        )
        """,
        (source_pk, model_id),
    ).fetchall()


def _source_values(plan: _SourcePlan, options: SyncOptions) -> tuple:
    _, parser_name, parser_version, parser_config = _parser(plan.source_type)
    return (
        plan.source_path,
        *plan.file_state,
        parser_name,
        parser_version,
        json.dumps(parser_config),
        schema.CHUNKER_NAME,
        schema.CHUNKER_VERSION,
        json.dumps({"max_chunk_chars": options.max_chunk_chars}),
        schema.NORMALISATION_VERSION,
        "{}",
        schema.utc_now(),
    )


def _chunk_values(candidate: chunking.ChunkCandidate) -> tuple:
    return (
        candidate.logical_key,
        candidate.ordinal,
        json.dumps(candidate.heading_path),
        candidate.symbol,
        candidate.body,
        candidate.semantic_input_hash,
        candidate.lexical_hash,
        candidate.content_type,
        candidate.physical_page,
        candidate.page_start_offset,
        candidate.page_end_offset,
        candidate.page_range_start,
        candidate.page_range_end,
        candidate.line_start,
        candidate.line_end,
        json.dumps(candidate.locator),
    )


def _load_units(
    conn: sqlite3.Connection, plan: _SourcePlan, report: SyncReport
) -> bool:
    """Fill a plan's chunk units, by parsing the source or, for a rechunk, from
    its retained page layouts, and record the outcome in the report.

    Returns False when the parser fails, so the sync skips the source.
    """
    if plan.action == "rechunk":  # no re-read of the source file
        for page_row in conn.execute(
            "SELECT physical_page, layout_json FROM pages "
            "WHERE source_pk = ? ORDER BY physical_page",
            (plan.source_pk,),
        ):
            if plan.source_type == "pdf":
                plan.units.extend(
                    pdf_parser.units_from_page_layout(
                        page_row["physical_page"], page_row["layout_json"]
                    )
                )
            else:
                plan.units.extend(units_from_layout(page_row["layout_json"]))
        report.sources_rechunked.append(plan.source_path)
        return True
    parser_module, _, _, parser_config = _parser(plan.source_type)
    # Parsers raise arbitrary errors on damaged files; skip the file so the
    # rest of the selection still syncs.
    try:
        result = parser_module.parse(plan.content_path, parser_config)
    except Exception as exc:  # noqa: BLE001
        report.skipped_sources[plan.source_path] = (
            f"cannot parse: {_source_error(exc, plan)}"
        )
        return False
    plan.units = result.units
    plan.pages = result.pages
    empty_pages = [page.physical_page for page in result.pages if not page.text.strip()]
    if plan.source_type == "pdf" and empty_pages:
        report.pages_without_text[plan.source_path] = empty_pages
    if plan.action == "add":
        report.sources_added.append(plan.source_path)
    else:
        report.sources_reparsed.append(plan.source_path)
    return True


def _embed_pending(
    conn: sqlite3.Connection,
    embedder: Embedder,
    model_id: str,
    pending: dict[str, str],
    reembed: bool,
) -> dict[str, list[float]]:
    """Embed the pending texts, keyed by semantic input hash, that have no
    embedding of the model yet, or all of them when ``reembed`` is set."""
    if pending and not reembed:
        # One JSON parameter, not one per hash: SQLite caps the parameters
        # in a statement, and a large source set exceeds that cap.
        cached = {
            row["semantic_input_hash"]
            for row in conn.execute(
                "SELECT semantic_input_hash FROM embeddings WHERE model_id = ? "
                "AND semantic_input_hash IN (SELECT value FROM json_each(?))",
                (model_id, json.dumps(list(pending))),
            )
        }
        pending = {
            semantic_hash: text
            for semantic_hash, text in pending.items()
            if semantic_hash not in cached
        }
    vectors = embedder.embed(list(pending.values())) if pending else []
    _validate_embedding_dimensions(vectors, schema.EMBEDDING_DIMENSIONS)
    return dict(zip(pending, vectors))


def _validate_embedding_dimensions(
    vectors: list[list[float]], expected_dimensions: int
) -> None:
    for index, vector in enumerate(vectors):
        if len(vector) != expected_dimensions:
            raise SyncError(
                f"embedding dimension mismatch for vector {index}: expected {expected_dimensions}, got {len(vector)}"
            )


def _lock_database(database_path: Path) -> int:
    """Wait for the exclusive sync and prune lock of a database.

    Two syncs that plan from the same database state would both insert the
    same sources, so a second sync or prune waits for the first to finish.
    The lock is an flock on ``<database>.lock`` beside the database, so it is
    POSIX only. Close the returned descriptor to release the lock.
    """
    import fcntl

    descriptor = os.open(
        f"{Path(database_path).resolve()}.lock", os.O_RDONLY | os.O_CREAT, 0o644
    )
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    return descriptor


def sync(
    sources_dir: Path,
    manifest_path: Path | Sequence[Path],
    database_path: Path,
    *,
    options: SyncOptions | None = None,
    embedder: Embedder | None = None,
    model_cache_dir: Path | None = None,
    only_relative_paths: set[str] | None = None,
) -> SyncReport:
    options = options or SyncOptions()
    sources_dir = Path(sources_dir).resolve()
    database_path = Path(database_path)

    rules = load_manifest_rules(manifest_path)
    if not (rules.explicit_paths or rules.include_globs):
        raise SyncError(
            "sync requires at least one [[source]] or [[include]] rule; "
            "[[exclude]] rules only narrow a selection"
        )
    selection = manifest_module.resolve_sources(sources_dir, rules)

    database_path.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_database(database_path)
    conn: sqlite3.Connection | None = None
    snapshot_root: Path | None = None
    try:
        conn = schema.connect(database_path)
        config = schema.ensure_schema(conn)
        snapshot_root = Path(
            tempfile.mkdtemp(
                prefix=".tracecite-source-snapshots-",
                dir=database_path.resolve().parent,
            )
        )
        if schema.EMBEDDING_DIMENSIONS != config.embedding_dimensions:
            raise SyncError(
                f"embedding dimensions {schema.EMBEDDING_DIMENSIONS} are incompatible with schema v{config.schema_version} "
                f"database dimensions {config.embedding_dimensions}"
            )
        model_id = schema.embedding_model_id(
            schema.EMBEDDING_MODEL, schema.EMBEDDING_REVISION
        )

        if embedder is None:
            cache_dir = model_cache_dir or (
                Path(database_path).resolve().parent / "model-cache"
            )
            embedder = EmbeddingModel(
                schema.EMBEDDING_MODEL, schema.EMBEDDING_REVISION, cache_dir
            )

        existing_sources = {
            row["path"]: row for row in conn.execute("SELECT * FROM sources").fetchall()
        }
        present_paths = set(selection.selected)
        selected_existing_paths = {
            path for path in existing_sources if rules.selects_path(path)
        }
        indexed_unselected_paths = set(existing_sources) - selected_existing_paths
        missing_selected_paths = selected_existing_paths - present_paths
        never_indexed_missing_paths = set(selection.missing_explicit_paths) - set(
            existing_sources
        )
        added_ids = present_paths - set(existing_sources)
        continuing_ids = present_paths & set(existing_sources)

        if only_relative_paths is not None:
            added_ids &= only_relative_paths
            continuing_ids &= only_relative_paths

        report = SyncReport()
        report.skipped_sources = {
            path: "symlink; sync reads only regular files"
            for path in selection.symlinks
            if only_relative_paths is None or path in only_relative_paths
        }
        for path in sorted(added_ids | continuing_ids):
            if not os.access(sources_dir / path, os.R_OK):
                report.skipped_sources[path] = "no read permission"
        added_ids -= report.skipped_sources.keys()
        continuing_ids -= report.skipped_sources.keys()

        # ---- rename detection: gone id <-> added id sharing an unambiguous hash ----
        observed_states: dict[str, tuple[Path, str, int, int]] = {}
        renames: dict[str, str] = {}
        rename_candidates = missing_selected_paths | indexed_unselected_paths
        if rename_candidates and added_ids:
            by_hash_gone: dict[str, list[str]] = defaultdict(list)
            for sid in rename_candidates:
                by_hash_gone[existing_sources[sid]["sha256"]].append(sid)
            by_hash_added: dict[str, list[str]] = defaultdict(list)
            for sid in added_ids:
                added_abs = sources_dir / sid
                captured = _capture_stable_file_state(added_abs)
                if captured is None:
                    raise _SourceChangedDuringSync
                file_hash, size_bytes, mtime_ns = captured
                observed_states[sid] = (added_abs, file_hash, size_bytes, mtime_ns)
                by_hash_added[file_hash].append(sid)
            for file_hash, gone_list in by_hash_gone.items():
                added_list = by_hash_added.get(file_hash, [])
                if len(gone_list) == 1 and len(added_list) == 1:
                    renames[gone_list[0]] = added_list[0]

        renamed_new_ids = set(renames.values())
        true_added_ids = added_ids - renamed_new_ids

        report.selected_missing_paths.extend(
            sorted(
                (missing_selected_paths | never_indexed_missing_paths)
                - set(renames.keys())
            )
        )
        report.missing_explicit_paths.extend(
            path
            for path in selection.missing_explicit_paths
            if only_relative_paths is None or path in only_relative_paths
        )
        report.indexed_unselected_paths.extend(
            sorted(indexed_unselected_paths - set(renames.keys()))
        )
        report.unmatched_globs.extend(selection.unmatched_globs)

        # ---- build per-source plans needing (re)parsing or rechunking ----
        plans: list[_SourcePlan] = []
        hint_updates: list[tuple[int, int, str]] = []  # (size, mtime, path)
        # (chunk_id, semantic_input_hash) pairs needing only a fresh embedding
        # mapping: the embedding model changed but the source did not.
        reembed_only_chunks: list[tuple[str, str]] = []
        pending_embeddings: dict[str, str] = {}  # semantic_input_hash -> body text

        # Adds come first so new sources get their source_pk in path order.
        for source_path in [*sorted(true_added_ids), *sorted(continuing_ids)]:
            abs_path = sources_dir / source_path
            source_type = manifest_module.SOURCE_TYPES[abs_path.suffix.lower()]
            row = existing_sources.get(source_path)
            action = "add"
            state = None
            if row is not None:
                state = _capture_stable_file_state(abs_path)
                if state is None:
                    raise _SourceChangedDuringSync
                observed_states[source_path] = (abs_path, *state)
                content_changed = state[0] != row["sha256"]
                if (
                    not content_changed
                    and _config_matches(row, options, source_type)
                    and not options.full
                ):
                    if state[1:] != (row["size_bytes"], row["mtime_ns"]):
                        hint_updates.append((*state[1:], source_path))
                    if not options.reembed:
                        missing_rows = _chunks_missing_active_embedding(
                            conn, row["source_pk"], model_id
                        )
                        if not missing_rows:
                            report.sources_unchanged.append(source_path)
                        for missing_row in missing_rows:
                            reembed_only_chunks.append(
                                (
                                    missing_row["chunk_id"],
                                    missing_row["semantic_input_hash"],
                                )
                            )
                            pending_embeddings.setdefault(
                                missing_row["semantic_input_hash"], missing_row["body"]
                            )
                        continue
                reparse = (
                    content_changed
                    or options.full
                    or (row["parser_name"], row["parser_version"])
                    != _parser(source_type)[1:3]
                )
                action = "reparse" if reparse else "rechunk"

            snapshot_path = None
            if action != "rechunk":
                snapshot = _capture_source_snapshot(abs_path, snapshot_root)
                # A continuing source must still hold the bytes just hashed.
                if snapshot is None or (state is not None and state != snapshot[1]):
                    raise _SourceChangedDuringSync
                snapshot_path, state = snapshot
                observed_states[source_path] = (abs_path, *state)
            assert state is not None
            plans.append(
                _SourcePlan(
                    source_path=source_path,
                    source_pk=None if row is None else row["source_pk"],
                    abs_path=abs_path,
                    source_type=source_type,
                    action=action,
                    file_state=state,
                    snapshot_path=snapshot_path,
                )
            )

        # ---- parse or rechunk each plan ----
        plans = [plan for plan in plans if _load_units(conn, plan, report)]

        # ---- build chunk candidates and diff against existing rows ----
        for plan in plans:
            groups = chunking.group_units(plan.units, max_chars=options.max_chunk_chars)
            candidates = chunking.build_chunk_candidates(
                groups,
                source_type=plan.source_type,
                normalisation_version=schema.NORMALISATION_VERSION,
            )
            existing_rows = conn.execute(
                "SELECT * FROM chunks WHERE source_pk = ?", (plan.source_pk,)
            ).fetchall()
            plan.matched, plan.deleted_chunk_ids, plan.new_candidates = _match_chunks(
                existing_rows, candidates
            )
            for row, candidate in plan.matched:
                if _needs_new_embedding(row, candidate, options):
                    pending_embeddings[candidate.semantic_input_hash] = candidate.body
            for candidate in plan.new_candidates:
                pending_embeddings[candidate.semantic_input_hash] = candidate.body

        hash_to_vector = _embed_pending(
            conn, embedder, model_id, pending_embeddings, options.reembed
        )
        report.embeddings_generated = len(hash_to_vector)

        if not (plans or hint_updates or renames or reembed_only_chunks):
            return report

        rendered_assets: dict[str, list] = {}
        # A new source has no source_pk until its row is inserted, so its
        # assets render into a staging directory renamed after the insert.
        staging_dirs: dict[str, Path] = {}
        generation_root = _asset_generation_root(database_path, uuid.uuid4().hex)
        for plan in plans:
            if (
                plan.action == "rechunk"
                or plan.source_type != "pdf"
                or not options.generate_assets
            ):
                continue
            if plan.source_pk is None:
                base_dir = generation_root / f".staging-{uuid.uuid4().hex}"
                staging_dirs[plan.source_path] = base_dir
            else:
                base_dir = generation_root / str(plan.source_pk)
            try:
                rendered_assets[plan.source_path] = _render_assets(plan, base_dir)
            except Exception as exc:
                shutil.rmtree(generation_root, ignore_errors=True)
                raise SyncError(
                    f"cannot render pages of {plan.source_path}: "
                    f"{_source_error(exc, plan)}"
                ) from exc

        # ==== single write transaction ====
        conn.execute("BEGIN IMMEDIATE")
        try:
            backend = vector_backend.SqliteVecBackend()

            # size/mtime hint-only updates for sources whose content, parser,
            # chunker, and normalisation metadata are all unchanged
            conn.executemany(
                "UPDATE sources SET size_bytes = ?, mtime_ns = ? WHERE path = ?",
                hint_updates,
            )

            # renames: relabel path while retaining internal source_pk
            for old_id, new_id in sorted(renames.items()):
                _, _, size_bytes, mtime_ns = observed_states[new_id]
                conn.execute(
                    "UPDATE sources SET path = ?, size_bytes = ?, mtime_ns = ? WHERE path = ?",
                    (new_id, size_bytes, mtime_ns, old_id),
                )
                report.sources_renamed.append((old_id, new_id))

            links: list[tuple[str, str]] = []  # (chunk_id, semantic_input_hash)
            for plan in plans:
                if plan.action == "add":
                    # A new source's row must exist before its chunks reference it.
                    plan.source_pk = conn.execute(
                        """
                        INSERT INTO sources (
                            path, sha256, size_bytes, mtime_ns,
                            parser_name, parser_version, parser_config,
                            chunker_name, chunker_version, chunker_config,
                            normalisation_version, normalisation_config,
                            indexed_at_utc, source_type, index_status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok')
                        """,
                        (*_source_values(plan, options), plan.source_type),
                    ).lastrowid
                    staging_dir = staging_dirs.get(plan.source_path)
                    if staging_dir is not None:
                        final_dir = staging_dir.with_name(str(plan.source_pk))
                        os.replace(staging_dir, final_dir)
                        rendered_assets[plan.source_path] = [
                            (final_dir / path.name, *rest)
                            for path, *rest in rendered_assets[plan.source_path]
                        ]
                else:
                    conn.execute(
                        """
                        UPDATE sources SET
                            path = ?, sha256 = ?, size_bytes = ?, mtime_ns = ?,
                            parser_name = ?, parser_version = ?, parser_config = ?,
                            chunker_name = ?, chunker_version = ?, chunker_config = ?,
                            normalisation_version = ?, normalisation_config = ?,
                            indexed_at_utc = ?, index_status = 'ok'
                        WHERE source_pk = ?
                        """,
                        (*_source_values(plan, options), plan.source_pk),
                    )

                conn.executemany(
                    "DELETE FROM chunks WHERE chunk_id = ?",
                    [(chunk_id,) for chunk_id in plan.deleted_chunk_ids],
                )
                conn.executemany(
                    """
                    UPDATE chunks SET
                        logical_key = ?, ordinal = ?, heading_path = ?, symbol = ?,
                        body = ?, semantic_input_hash = ?, lexical_hash = ?,
                        content_type = ?, physical_page = ?, page_start_offset = ?,
                        page_end_offset = ?, page_range_start = ?, page_range_end = ?,
                        line_start = ?, line_end = ?, locator_json = ?
                    WHERE chunk_id = ?
                    """,
                    [
                        (*_chunk_values(candidate), row["chunk_id"])
                        for row, candidate in plan.matched
                    ],
                )
                relinked = [
                    (row["chunk_id"], candidate.semantic_input_hash)
                    for row, candidate in plan.matched
                    if _needs_new_embedding(row, candidate, options)
                ]
                conn.executemany(
                    "DELETE FROM chunk_embeddings WHERE chunk_id = ?",
                    [(chunk_id,) for chunk_id, _ in relinked],
                )
                new_chunks = [
                    (uuid.uuid4().hex, candidate) for candidate in plan.new_candidates
                ]
                conn.executemany(
                    """
                    INSERT INTO chunks (
                        chunk_id, source_pk, logical_key, ordinal, heading_path, symbol,
                        body, semantic_input_hash, lexical_hash, content_type,
                        physical_page, page_start_offset, page_end_offset,
                        page_range_start, page_range_end, line_start, line_end, locator_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (chunk_id, plan.source_pk, *_chunk_values(candidate))
                        for chunk_id, candidate in new_chunks
                    ],
                )
                links.extend(relinked)
                links.extend(
                    (chunk_id, candidate.semantic_input_hash)
                    for chunk_id, candidate in new_chunks
                )
                report.chunks_deleted += len(plan.deleted_chunk_ids)
                report.chunks_updated += len(plan.matched)
                report.chunks_added += len(new_chunks)

                # pages and assets change only when the source was parsed
                if plan.action != "rechunk":
                    conn.execute(
                        "DELETE FROM pages WHERE source_pk = ?", (plan.source_pk,)
                    )
                    conn.executemany(
                        """
                        INSERT INTO pages (
                            source_pk, physical_page, printed_label, text,
                            extraction_method, extraction_status, section_candidates, layout_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                plan.source_pk,
                                page.physical_page,
                                page.printed_label,
                                page.text,
                                page.extraction_method,
                                page.extraction_status,
                                json.dumps(page.section_candidates),
                                None
                                if page.layout is None
                                else json.dumps(page.layout),
                            )
                            for page in plan.pages
                        ],
                    )
                    if plan.source_type == "pdf" and options.generate_assets:
                        _persist_assets(
                            conn,
                            plan,
                            rendered_assets.get(plan.source_path, []),
                            database_path,
                        )

            # Link each new or changed chunk, then each chunk of an unchanged
            # source that lacks an embedding of the active model.
            for chunk_id, semantic_input_hash in [*links, *reembed_only_chunks]:
                _ensure_embedding(
                    conn,
                    backend,
                    model_id,
                    hash_to_vector,
                    chunk_id,
                    semantic_input_hash,
                )

            if not _observed_sources_match(observed_states):
                raise _SourceChangedDuringSync

            schema.touch_config(conn)
            conn.execute("COMMIT")
        except Exception:
            with contextlib.suppress(sqlite3.Error):
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
            shutil.rmtree(generation_root, ignore_errors=True)
            raise

        if options.cleanup_asset_generations:
            report.cleanup_warnings.extend(
                cleanup_asset_generations(conn, database_path)
            )

        return report
    except _SourceChangedDuringSync:
        return SyncReport(status="aborted-source-changed")
    finally:
        if conn is not None:
            conn.close()
        if snapshot_root is not None:
            shutil.rmtree(snapshot_root, ignore_errors=True)
        os.close(lock)


def plan_prune(
    conn: sqlite3.Connection, selected_paths: Collection[str]
) -> tuple[str, ...]:
    """Return the indexed source paths outside ``selected_paths``."""
    rows = conn.execute("SELECT path FROM sources ORDER BY path").fetchall()
    selected = set(selected_paths)
    return tuple(row["path"] for row in rows if row["path"] not in selected)


def _canonical_asset_parts(
    database_path: Path, stored_asset_path: str, *, validate_filesystem: bool = True
) -> tuple[str, ...]:
    if validate_filesystem:
        resolved = schema.resolve_asset_path(database_path, stored_asset_path)
    else:
        resolved = (
            Path(database_path).resolve().parent.joinpath(*stored_asset_path.split("/"))
        )
    try:
        relative = resolved.relative_to(Path(database_path).resolve().parent)
    except ValueError as exc:
        raise ValueError(
            f"asset identifier escapes database asset root: {stored_asset_path!r}"
        ) from exc
    return relative.parts


def _prune_asset_target(
    database_path: Path,
    source_pk: int,
    stored_asset_path: str,
    *,
    validate_filesystem: bool = True,
) -> Path:
    parts = _canonical_asset_parts(
        database_path, stored_asset_path, validate_filesystem=validate_filesystem
    )
    if len(parts) < 5 or parts[:2] != ("imgs", "generations"):
        raise ValueError(
            "asset identifier must have shape "
            f"imgs/generations/<generation>/<source_pk>/<asset-file>: {stored_asset_path!r}"
        )
    generation, stored_source_pk = parts[2], parts[3]
    if not stored_source_pk.isdecimal() or int(stored_source_pk) != source_pk:
        raise ValueError(
            f"asset identifier source association does not match source_pk {source_pk}: {stored_asset_path!r}"
        )
    return (
        schema.imgs_dir(database_path) / "generations" / generation / stored_source_pk
    )


def validate_prune_plan(
    conn: sqlite3.Connection, database_path: Path, plan: tuple[str, ...]
) -> set[Path]:
    """Return the asset directories the plan would remove, or raise if any stored asset path is unsafe."""
    targets_by_source: dict[int, set[Path]] = defaultdict(set)
    for path in plan:
        for row in conn.execute(
            "SELECT source_pk, asset_path FROM assets JOIN sources USING (source_pk) WHERE path = ?",
            (path,),
        ):
            targets_by_source[row["source_pk"]].add(
                _prune_asset_target(database_path, row["source_pk"], row["asset_path"])
            )
    for source_pk, source_targets in targets_by_source.items():
        if len(source_targets) > 1:
            raise ValueError(
                f"asset identifiers for source_pk {source_pk} span multiple generation/source directories"
            )
    return set().union(*targets_by_source.values())


def apply_prune(
    conn: sqlite3.Connection, database_path: Path, plan: tuple[str, ...]
) -> list[str]:
    lock = _lock_database(database_path)
    try:
        return _apply_prune(conn, database_path, plan)
    finally:
        os.close(lock)


def _apply_prune(
    conn: sqlite3.Connection, database_path: Path, plan: tuple[str, ...]
) -> list[str]:
    backend = vector_backend.SqliteVecBackend()
    conn.execute("BEGIN IMMEDIATE")
    try:
        pruned_asset_targets = validate_prune_plan(conn, database_path, plan)
        conn.executemany(
            "DELETE FROM sources WHERE path = ?", [(path,) for path in plan]
        )
        orphans = "SELECT embedding_id FROM embeddings WHERE embedding_id NOT IN (SELECT embedding_id FROM chunk_embeddings)"
        backend.delete(conn, [row["embedding_id"] for row in conn.execute(orphans)])
        conn.execute(f"DELETE FROM embeddings WHERE embedding_id IN ({orphans})")
        schema.touch_config(conn)
        conn.execute("COMMIT")
    except Exception:
        with contextlib.suppress(sqlite3.Error):
            if conn.in_transaction:
                conn.execute("ROLLBACK")
        raise
    leaks: list[str] = []
    referenced_dirs = {
        _prune_asset_target(
            database_path,
            row["source_pk"],
            row["asset_path"],
            validate_filesystem=False,
        )
        for row in conn.execute("SELECT source_pk, asset_path FROM assets").fetchall()
    }
    for asset_dir in sorted(pruned_asset_targets, key=str):
        if asset_dir in referenced_dirs or not asset_dir.exists():
            continue
        try:
            shutil.rmtree(asset_dir)
        except OSError as exc:
            leaks.append(f"failed to remove pruned asset directory {asset_dir}: {exc}")
    try:
        leaks.extend(cleanup_asset_generations(conn, database_path))
    except Exception as exc:  # noqa: BLE001
        leaks.append(f"failed to clean unreferenced asset generations: {exc}")
    # Deleted rows leave free pages inside the file; VACUUM returns them to
    # the filesystem so a prune also shrinks the database.
    try:
        conn.execute("VACUUM")
    except sqlite3.Error as exc:
        leaks.append(f"failed to vacuum the database after pruning: {exc}")
    return leaks


def _ensure_embedding(
    conn: sqlite3.Connection,
    backend: vector_backend.SqliteVecBackend,
    model_id: str,
    hash_to_vector: dict[str, list[float]],
    chunk_id: str,
    semantic_input_hash: str,
) -> None:
    """Link a chunk to the model's embedding of its text, storing a vector
    generated in this sync."""
    row = conn.execute(
        "SELECT embedding_id FROM embeddings WHERE model_id = ? AND semantic_input_hash = ?",
        (model_id, semantic_input_hash),
    ).fetchone()
    vector = hash_to_vector.get(semantic_input_hash)
    if row is None and vector is None:
        raise SyncError(
            f"no embedding available for semantic_input_hash={semantic_input_hash!r}; "
            "this indicates a bug in the pending-embedding queue"
        )
    if row is None:
        embedding_id = conn.execute(
            "INSERT INTO embeddings(model_id, semantic_input_hash, created_at_utc) VALUES (?, ?, ?)",
            (model_id, semantic_input_hash, schema.utc_now()),
        ).lastrowid
        assert embedding_id is not None
    else:
        embedding_id = row["embedding_id"]
    if vector is not None:
        backend.upsert(conn, embedding_id, vector)
    conn.execute(
        "INSERT OR IGNORE INTO chunk_embeddings(chunk_id, embedding_id) VALUES (?, ?)",
        (chunk_id, embedding_id),
    )


def _asset_generation_root(database_path: Path, generation: str) -> Path:
    return schema.resolve_asset_path(database_path, f"imgs/generations/{generation}")


def _render_assets(plan: _SourcePlan, base_dir: Path) -> list[tuple[Path, object, str]]:
    base_dir.mkdir(parents=True, exist_ok=False)
    rendered: list[tuple[Path, object, str]] = []
    for physical_page in sorted({page.physical_page for page in plan.pages}):
        page_render = pdf_parser.render_page(plan.content_path, physical_page)
        crops = pdf_parser.render_figure_crops(plan.content_path, physical_page)
        for asset in [page_render, *crops]:
            name = asset.label or f"page-{physical_page:04d}"
            asset_path = base_dir / f"{name}.{asset.ext}"
            asset_path.write_bytes(asset.image_bytes)
            rendered.append((asset_path, asset, file_sha256(asset_path)))
    return rendered


def _persist_assets(
    conn: sqlite3.Connection, plan: _SourcePlan, rendered_assets, database_path: Path
) -> None:
    assert plan.source_pk is not None
    conn.execute("DELETE FROM assets WHERE source_pk = ?", (plan.source_pk,))
    database_parent = Path(database_path).resolve().parent
    rows = []
    for asset_path, asset, sha256 in rendered_assets:
        asset_identifier = asset_path.resolve().relative_to(database_parent).as_posix()
        schema.resolve_asset_path(database_path, asset_identifier)
        rows.append(
            (
                f"{plan.source_path}:{asset_path.stem}",
                plan.source_pk,
                asset.physical_page,
                asset_identifier,
                sha256,
                asset.width,
                asset.height,
                asset.asset_type,
                asset.label,
                asset.nearby_text,
                json.dumps(asset.bbox) if asset.bbox else None,
            )
        )
    # NOTE: caption, ocr_text and visual_description are always NULL; OCR
    # fallback writes page and chunk text only.
    conn.executemany(
        """
        INSERT INTO assets (
            asset_id, source_pk, physical_page, asset_path, sha256, width, height,
            asset_type, label, caption, nearby_text, ocr_text, visual_description, bbox_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, ?)
        """,
        rows,
    )


def referenced_asset_generations(
    conn: sqlite3.Connection, database_path: Path
) -> set[Path]:
    rows = conn.execute("SELECT asset_path FROM assets").fetchall()
    database_parent = Path(database_path).resolve().parent
    referenced: set[Path] = set()
    for row in rows:
        parts = _canonical_asset_parts(
            database_path,
            row["asset_path"],
            validate_filesystem=False,
        )
        if len(parts) < 3 or parts[:2] != ("imgs", "generations"):
            raise ValueError(
                f"asset identifier has the wrong generation root: {row['asset_path']!r}"
            )
        referenced.add(database_parent.joinpath(*parts[:3]))
    return referenced


def cleanup_asset_generations(
    conn: sqlite3.Connection, database_path: Path
) -> list[str]:
    leaks: list[str] = []
    root = schema.imgs_dir(database_path) / "generations"
    if not root.exists():
        return leaks
    referenced = referenced_asset_generations(conn, database_path)
    for generation in root.iterdir():
        symlink = generation.is_symlink()
        if not symlink and generation in referenced:
            continue
        kind = (
            "invalid asset generation symlink"
            if symlink
            else "unreferenced asset generation"
        )
        try:
            if symlink:
                generation.unlink()
            else:
                shutil.rmtree(generation)
        except OSError as exc:
            leaks.append(f"failed to remove {kind} {generation}: {exc}")
    return leaks


def integrity_check(conn: sqlite3.Connection) -> list[str]:
    issues: list[str] = []
    database_path = Path(conn.execute("PRAGMA database_list").fetchone()["file"])

    fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    chunks_count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    if fts_count != chunks_count:
        issues.append(
            f"chunks_fts has {fts_count} rows but chunks has {chunks_count} rows"
        )

    orphan_chunk_embeddings = conn.execute(
        """
        SELECT ce.chunk_id FROM chunk_embeddings ce
        LEFT JOIN chunks c ON c.chunk_id = ce.chunk_id
        WHERE c.chunk_id IS NULL
        """
    )
    issues += [
        f"chunk_embeddings references missing chunk {row['chunk_id']}"
        for row in orphan_chunk_embeddings
    ]
    issues += vector_backend.SqliteVecBackend().integrity_check(conn)

    for row in conn.execute(
        "SELECT asset_id, asset_path, sha256 FROM assets"
    ).fetchall():
        asset_path = schema.resolve_asset_path(database_path, row["asset_path"])
        if not asset_path.is_file():
            issues.append(
                f"asset {row['asset_id']} references missing file {row['asset_path']}"
            )
            continue
        actual = file_sha256(asset_path)
        if actual != row["sha256"]:
            issues.append(
                f"asset {row['asset_id']} hash mismatch: expected {row['sha256']}, got {actual}"
            )

    return issues
