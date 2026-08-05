"""Incremental, transaction-safe synchronisation lifecycle (plan 0006).

    scan filesystem
        |
    identify candidate changes from mtime and size
        |
    hash candidate files
        |
    parse only genuinely changed or invalidated files
        |
    compare old and new chunks
        |
    reuse or generate only missing embeddings
        |
    recheck source state
        |
    apply one SQLite transaction

Embeddings are generated before ``BEGIN IMMEDIATE``. If embedding fails, the
exception propagates before any write happens, so the database is left
unchanged. If a source's file changes between the initial parse and the
pre-commit recheck, the whole sync call aborts before opening the
transaction (status ``"aborted-source-changed"``) so callers can retry.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from collections.abc import Collection, Sequence
from pathlib import Path
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import tomllib
import uuid

from . import chunking, manifest as manifest_module, schema, vector_backend
from .embedding import Embedder, EmbeddingModel
from .parsers import markdown as markdown_parser
from .parsers import pdf as pdf_parser
from .parsers import workbook as workbook_parser
from .parsers.base import ParsedChunkUnit

SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".xlsx": "workbook",
    ".xlsm": "workbook",
}
ASSET_EVENT_HOOK = None


def _asset_event(name: str) -> None:
    if ASSET_EVENT_HOOK is not None:
        ASSET_EVENT_HOOK(name)


class SyncError(RuntimeError):
    """A sync precondition failed (bad manifest, unmapped file, etc.)."""


class _SourceChangedDuringSync(RuntimeError):
    """A source no longer matches the snapshot used to build the transaction."""


@dataclass
class SyncOptions:
    max_chunk_chars: int = chunking.DEFAULT_MAX_CHUNK_CHARS
    parser_version_pdf: str = schema.PARSER_VERSION_PDF
    parser_version_markdown: str = schema.PARSER_VERSION_MARKDOWN
    parser_version_workbook: str = schema.PARSER_VERSION_WORKBOOK
    chunker_version: str = schema.CHUNKER_VERSION
    normalisation_version: str = schema.NORMALISATION_VERSION
    embedding_model: str = schema.EMBEDDING_MODEL
    embedding_revision: str = schema.EMBEDDING_REVISION
    embedding_dimensions: int = schema.EMBEDDING_DIMENSIONS
    generate_assets: bool = True
    cleanup_asset_generations: bool = True
    full: bool = False
    reembed: bool = False
    ocr_lang: str = pdf_parser.DEFAULT_OCR_LANG

    @property
    def model_id(self) -> str:
        return schema.embedding_model_id(self.embedding_model, self.embedding_revision)

    def parser_version(self, source_type: str) -> str:
        if source_type == "pdf":
            return self.parser_version_pdf
        if source_type == "markdown":
            return self.parser_version_markdown
        if source_type == "workbook":
            return self.parser_version_workbook
        raise SyncError(f"unsupported source type: {source_type}")

    def parser_name(self, source_type: str) -> str:
        if source_type == "pdf":
            return schema.PARSER_NAME_PDF
        if source_type == "markdown":
            return schema.PARSER_NAME_MARKDOWN
        if source_type == "workbook":
            return schema.PARSER_NAME_WORKBOOK
        raise SyncError(f"unsupported source type: {source_type}")


@dataclass
class SyncReport:
    status: str = "ok"
    sources_added: list[str] = field(default_factory=list)
    sources_reparsed: list[str] = field(default_factory=list)
    sources_rechunked: list[str] = field(default_factory=list)
    sources_unchanged: list[str] = field(default_factory=list)
    sources_renamed: list[tuple[str, str]] = field(default_factory=list)
    sources_deleted: list[str] = field(default_factory=list)
    selected_missing_paths: list[str] = field(default_factory=list)
    indexed_unselected_paths: list[str] = field(default_factory=list)
    unmatched_globs: list[str] = field(default_factory=list)
    cleanup_warnings: list[str] = field(default_factory=list)
    chunks_added: int = 0
    chunks_updated: int = 0
    chunks_deleted: int = 0
    embeddings_generated: int = 0

    @property
    def wrote_anything(self) -> bool:
        return bool(
            self.sources_added
            or self.sources_reparsed
            or self.sources_rechunked
            or self.sources_renamed
            or self.sources_deleted
        )


@dataclass
class AssetGeneration:
    generation_id: str
    root: Path
    referenced_files: tuple[Path, ...] = ()
    staging_dir: Path | None = None

    def discard(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def finalize_new_source(self, source_pk: int) -> dict[Path, Path]:
        if self.staging_dir is None:
            return {}
        final_dir = self.root / str(source_pk)
        os.replace(self.staging_dir, final_dir)
        mapping = {path: final_dir / path.name for path in self.referenced_files}
        self.referenced_files = tuple(mapping[path] for path in self.referenced_files)
        self.staging_dir = None
        return mapping


def load_manifest_rules(manifest_paths: Path | Sequence[Path]) -> manifest_module.ManifestRules:
    paths = list(manifest_paths) if isinstance(manifest_paths, (list, tuple)) else [manifest_paths]
    return manifest_module.merge_manifests(paths)


def discover_source_files(sources_dir: Path, rules: manifest_module.ManifestRules) -> dict[str, Path]:
    sources_dir = Path(sources_dir).resolve()
    discovered: dict[str, Path] = {}
    candidates: set[Path] = set()
    for relative in rules.explicit_paths:
        candidates.add(sources_dir / relative)
    for pattern in rules.include_globs:
        candidates.update(sources_dir.glob(pattern))
    for path in sorted(candidates):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(sources_dir)
        except ValueError:
            continue
        relative = resolved.relative_to(sources_dir).as_posix()
        if rules.selects_path(relative):
            discovered[relative] = resolved
    return discovered


def source_type_for(path: Path) -> str:
    return SUPPORTED_EXTENSIONS[Path(path).suffix.lower()]


def _parser_config_for(source_type: str, options: SyncOptions) -> dict:
    if source_type == "pdf":
        return {"ocr_lang": options.ocr_lang}
    return {}


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path) -> tuple[int, int]:
    info = Path(path).stat()
    return info.st_size, info.st_mtime_ns


def _capture_stable_file_state(path: Path) -> tuple[str, int, int] | None:
    """Hash one stable, non-symlink file identity.

    The descriptor identity and the path identity must still agree after the
    read.  This catches path replacement as well as ordinary in-place writes.
    """

    path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except (FileNotFoundError, OSError):
        return None
    try:
        before = os.fstat(descriptor)
        digest = hashlib.sha256()
        while block := os.read(descriptor, 1 << 20):
            digest.update(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after:
        return None
    try:
        current = os.stat(path, follow_symlinks=False)
    except (FileNotFoundError, OSError):
        return None
    if stat.S_ISLNK(current.st_mode):
        return None
    current_identity = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
    if current_identity != identity_after:
        return None
    return digest.hexdigest(), after.st_size, after.st_mtime_ns


@dataclass(frozen=True)
class _SourceSnapshot:
    path: Path
    sha256: str
    size_bytes: int
    mtime_ns: int


def _capture_source_snapshot(path: Path, snapshot_root: Path) -> _SourceSnapshot | None:
    """Copy one stable source into an immutable per-sync parsing snapshot."""

    path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except (FileNotFoundError, OSError):
        return None
    snapshot_path = snapshot_root / f"{uuid.uuid4().hex}{path.suffix.lower()}"
    try:
        before = os.fstat(descriptor)
        digest = hashlib.sha256()
        with snapshot_path.open("xb") as output:
            while block := os.read(descriptor, 1 << 20):
                digest.update(block)
                output.write(block)
        after = os.fstat(descriptor)
    except Exception:
        snapshot_path.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after:
        snapshot_path.unlink(missing_ok=True)
        return None
    try:
        current = os.stat(path, follow_symlinks=False)
    except (FileNotFoundError, OSError):
        snapshot_path.unlink(missing_ok=True)
        return None
    if stat.S_ISLNK(current.st_mode):
        snapshot_path.unlink(missing_ok=True)
        return None
    current_identity = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
    if current_identity != identity_after:
        snapshot_path.unlink(missing_ok=True)
        return None
    expected = (digest.hexdigest(), after.st_size, after.st_mtime_ns)
    if _capture_stable_file_state(path) != expected:
        snapshot_path.unlink(missing_ok=True)
        return None
    return _SourceSnapshot(snapshot_path, *expected)


def _source_matches(path: Path, expected: tuple[str, int, int]) -> bool:
    return _capture_stable_file_state(path) == expected


@dataclass
class _SourcePlan:
    source_path: str
    source_pk: int | None
    relative_path: str
    abs_path: Path
    source_type: str
    action: str  # "add" | "reparse" | "rechunk" | "renormalise-only"
    sha256: str
    size_bytes: int
    mtime_ns: int
    parser_config: dict
    chunker_config: dict
    normalisation_config: dict
    snapshot_path: Path | None = None
    units: list[ParsedChunkUnit] = field(default_factory=list)
    pages: list = field(default_factory=list)
    assets: list = field(default_factory=list)

    @property
    def content_path(self) -> Path:
        return self.snapshot_path or self.abs_path


def _match_chunks(existing_rows: list[sqlite3.Row], candidates: list[chunking.ChunkCandidate]):
    """Three-pass chunk matching (plan 0006)."""

    existing_by_key: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in existing_rows:
        existing_by_key[row["logical_key"]].append(row)

    matched: list[tuple[sqlite3.Row, chunking.ChunkCandidate]] = []
    used_existing_ids: set[str] = set()
    remaining_candidates: list[chunking.ChunkCandidate] = []

    for candidate in candidates:
        row = None
        for bucket_row in existing_by_key.get(candidate.logical_key, []):
            if bucket_row["chunk_id"] not in used_existing_ids:
                row = bucket_row
                break
        if row is not None:
            used_existing_ids.add(row["chunk_id"])
            matched.append((row, candidate))
        else:
            remaining_candidates.append(candidate)

    remaining_existing = [row for row in existing_rows if row["chunk_id"] not in used_existing_ids]

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

    new_candidates = [c for c in remaining_candidates if id(c) not in consumed_candidate_ids]
    to_delete_chunk_ids = [row["chunk_id"] for row in still_remaining_existing]
    return matched, to_delete_chunk_ids, new_candidates


def _config_matches(row: sqlite3.Row, options: SyncOptions, source_type: str) -> bool:
    parser_name = options.parser_name(source_type)
    parser_version = options.parser_version(source_type)
    return (
        row["parser_name"] == parser_name
        and row["parser_version"] == parser_version
        and row["chunker_version"] == options.chunker_version
        and row["normalisation_version"] == options.normalisation_version
        and json.loads(row["chunker_config"]).get("max_chunk_chars") == options.max_chunk_chars
    )


def _chunks_missing_active_embedding(conn: sqlite3.Connection, source_pk: int, model_id: str):
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


def _validate_embedding_dimensions(vectors: list[list[float]], expected_dimensions: int) -> None:
    for index, vector in enumerate(vectors):
        if len(vector) != expected_dimensions:
            raise SyncError(
                f"embedding dimension mismatch for vector {index}: expected {expected_dimensions}, got {len(vector)}"
            )


@dataclass(frozen=True)
class PrunePlan:
    paths: tuple[str, ...]


@dataclass(frozen=True)
class _PruneAssetTarget:
    generation: str
    source_pk: int
    source_dir: Path


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
    discovered = discover_source_files(sources_dir, rules)
    manifest = {path: path for path in sorted(set(discovered) | set(rules.explicit_paths)) if rules.selects_path(path)}

    conn = schema.connect(database_path)
    snapshot_root: Path | None = None
    try:
        config = schema.ensure_schema(conn)
        snapshot_root = Path(
            tempfile.mkdtemp(
                prefix=".tracecite-source-snapshots-",
                dir=database_path.resolve().parent,
            )
        )
        if options.embedding_dimensions != config.embedding_dimensions:
            raise SyncError(
                f"embedding dimensions {options.embedding_dimensions} are incompatible with schema v{config.schema_version} "
                f"database dimensions {config.embedding_dimensions}"
            )
        active_config_changed = (
            options.embedding_model != config.embedding_model
            or options.embedding_revision != config.embedding_revision
            or options.embedding_dimensions != config.embedding_dimensions
        )

        if embedder is None:
            cache_dir = model_cache_dir or (Path(database_path).resolve().parent / "model-cache")
            embedder = EmbeddingModel(options.embedding_model, options.embedding_revision, cache_dir)

        existing_sources = {row["path"]: row for row in conn.execute("SELECT * FROM sources").fetchall()}
        selection = manifest_module.resolve_sources(sources_dir, rules, indexed_paths=existing_sources)
        present_paths = {path for path in manifest if path in discovered}
        selected_existing_paths = {path for path in existing_sources if rules.selects_path(path)}
        indexed_unselected_paths = set(existing_sources) - selected_existing_paths
        missing_selected_paths = selected_existing_paths - present_paths
        never_indexed_missing_paths = set(selection.missing_explicit_paths) - set(existing_sources)
        added_ids = present_paths - set(existing_sources)
        continuing_ids = present_paths & set(existing_sources)

        if only_relative_paths is not None:
            scoped_ids = {path for path in manifest if path in only_relative_paths}
            added_ids &= scoped_ids
            continuing_ids &= scoped_ids

        # ---- rename detection: gone id <-> added id sharing an unambiguous hash ----
        observed_states: dict[str, tuple[Path, str, int, int]] = {}
        renames: dict[str, str] = {}
        rename_rechecks: dict[str, tuple[Path, str, int, int]] = {}
        rename_candidates = missing_selected_paths | indexed_unselected_paths
        if rename_candidates and added_ids:
            by_hash_gone: dict[str, list[str]] = defaultdict(list)
            for sid in rename_candidates:
                by_hash_gone[existing_sources[sid]["sha256"]].append(sid)
            by_hash_added: dict[str, list[str]] = defaultdict(list)
            added_hashes: dict[str, str] = {}
            added_stats: dict[str, tuple[int, int]] = {}
            for sid in added_ids:
                added_abs = sources_dir / manifest[sid]
                captured = _capture_stable_file_state(added_abs)
                if captured is None:
                    return SyncReport(status="aborted-source-changed")
                file_hash, size_bytes, mtime_ns = captured
                observed_states[sid] = (added_abs, file_hash, size_bytes, mtime_ns)
                added_hashes[sid] = file_hash
                added_stats[sid] = (size_bytes, mtime_ns)
                by_hash_added[file_hash].append(sid)
            for file_hash, gone_list in by_hash_gone.items():
                added_list = by_hash_added.get(file_hash, [])
                if len(gone_list) == 1 and len(added_list) == 1:
                    renames[gone_list[0]] = added_list[0]
                    new_id = added_list[0]
                    size_bytes, mtime_ns = added_stats[new_id]
                    rename_rechecks[new_id] = (sources_dir / manifest[new_id], file_hash, size_bytes, mtime_ns)

        renamed_new_ids = set(renames.values())
        true_added_ids = added_ids - renamed_new_ids
        true_deleted_ids: set[str] = set()

        report = SyncReport()
        report.selected_missing_paths.extend(sorted((missing_selected_paths | never_indexed_missing_paths) - set(renames.keys())))
        report.indexed_unselected_paths.extend(sorted(indexed_unselected_paths - set(renames.keys())))
        report.unmatched_globs.extend(selection.unmatched_globs)

        # ---- build per-source plans needing (re)parsing or rechunking ----
        plans: list[_SourcePlan] = []
        hint_updates: list[tuple[str, str, int, int]] = []
        # (chunk_id, semantic_input_hash) pairs needing only a fresh embedding
        # mapping -- e.g. the embedding model changed but nothing else did,
        # so the source is otherwise untouched (plan 0006: "Embedding model
        # or dimensions: Re-embed only").
        reembed_only_chunks: list[tuple[str, str]] = []
        pending_embeddings: dict[str, str] = {}  # semantic_input_hash -> body text

        for source_path in sorted(true_added_ids):
            relative_path = manifest[source_path]
            abs_path = sources_dir / relative_path
            source_type = source_type_for(abs_path)
            snapshot = _capture_source_snapshot(abs_path, snapshot_root)
            if snapshot is None:
                return SyncReport(status="aborted-source-changed")
            file_hash = snapshot.sha256
            size_bytes = snapshot.size_bytes
            mtime_ns = snapshot.mtime_ns
            observed_states[source_path] = (abs_path, file_hash, size_bytes, mtime_ns)
            plans.append(
                _SourcePlan(
                    source_path=source_path,
                    source_pk=None,
                    relative_path=relative_path,
                    abs_path=abs_path,
                    source_type=source_type,
                    action="add",
                    sha256=file_hash,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                    parser_config=_parser_config_for(source_type, options),
                    chunker_config={"max_chunk_chars": options.max_chunk_chars},
                    normalisation_config={},
                    snapshot_path=snapshot.path,
                )
            )

        for source_path in sorted(continuing_ids):
            relative_path = manifest[source_path]
            abs_path = sources_dir / relative_path
            source_type = source_type_for(abs_path)
            row = existing_sources[source_path]
            source_pk = row["source_pk"]
            captured = _capture_stable_file_state(abs_path)
            if captured is None:
                return SyncReport(status="aborted-source-changed")
            file_hash, size_bytes, mtime_ns = captured
            observed_states[source_path] = (abs_path, file_hash, size_bytes, mtime_ns)

            config_matches = _config_matches(row, options, source_type)
            fast_unchanged = (
                not options.full
                and not options.reembed
                and config_matches
                and file_hash == row["sha256"]
                and size_bytes == row["size_bytes"]
                and mtime_ns == row["mtime_ns"]
                and relative_path == row["path"]
            )
            if fast_unchanged:
                missing_rows = _chunks_missing_active_embedding(conn, source_pk, options.model_id)
                if not missing_rows:
                    report.sources_unchanged.append(source_path)
                    continue
                # Nothing about the source, its parse, or its chunks changed
                # -- only the active embedding model lacks coverage for it.
                # Top up embeddings for exactly these chunks; do not reparse
                # or rechunk, and do not touch any other model's rows.
                for missing_row in missing_rows:
                    reembed_only_chunks.append(
                        (missing_row["chunk_id"], missing_row["semantic_input_hash"])
                    )
                    pending_embeddings.setdefault(
                        missing_row["semantic_input_hash"], missing_row["body"]
                    )
                continue

            content_changed = file_hash != row["sha256"]
            path_changed = relative_path != row["path"]

            if not content_changed and config_matches and not options.full:
                if path_changed or size_bytes != row["size_bytes"] or mtime_ns != row["mtime_ns"]:
                    hint_updates.append((source_path, relative_path, size_bytes, mtime_ns))
                if not options.reembed:
                    report.sources_unchanged.append(source_path)
                    continue

            needs_full_reparse = content_changed or row["parser_name"] != options.parser_name(
                source_type
            ) or row["parser_version"] != options.parser_version(source_type) or options.full

            action = "reparse" if needs_full_reparse else "rechunk"
            snapshot = None
            if action == "reparse":
                snapshot = _capture_source_snapshot(abs_path, snapshot_root)
                if snapshot is None or (
                    snapshot.sha256,
                    snapshot.size_bytes,
                    snapshot.mtime_ns,
                ) != captured:
                    return SyncReport(status="aborted-source-changed")
                observed_states[source_path] = (
                    abs_path,
                    snapshot.sha256,
                    snapshot.size_bytes,
                    snapshot.mtime_ns,
                )
            plans.append(
                _SourcePlan(
                    source_path=source_path,
                    source_pk=source_pk,
                    relative_path=relative_path,
                    abs_path=abs_path,
                    source_type=source_type,
                    action=action,
                    sha256=file_hash,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                    parser_config=_parser_config_for(source_type, options),
                    chunker_config={"max_chunk_chars": options.max_chunk_chars},
                    normalisation_config={},
                    snapshot_path=snapshot.path if snapshot is not None else None,
                )
            )

        # ---- parse or rechunk each plan ----
        for plan in plans:
            if plan.action in ("add", "reparse"):
                parser_module = {
                    "pdf": pdf_parser,
                    "markdown": markdown_parser,
                    "workbook": workbook_parser,
                }[plan.source_type]
                result = parser_module.parse(plan.content_path, plan.parser_config)
                plan.units = result.units
                plan.pages = result.pages
                plan.assets = result.assets
                if plan.action == "add":
                    report.sources_added.append(plan.source_path)
                else:
                    report.sources_reparsed.append(plan.source_path)
            else:  # rechunk from retained extraction, no re-read of the source file
                assert plan.source_pk is not None
                page_rows = conn.execute(
                    "SELECT * FROM pages WHERE source_pk = ? ORDER BY physical_page",
                    (plan.source_pk,),
                ).fetchall()
                units: list[ParsedChunkUnit] = []
                for page_row in page_rows:
                    if plan.source_type == "pdf":
                        units.extend(
                            pdf_parser.units_from_page_layout(
                                plan.source_path, page_row["physical_page"], page_row["layout_json"]
                            )
                        )
                    elif plan.source_type == "markdown":
                        units.extend(markdown_parser.units_from_page_layout(page_row["layout_json"]))
                    else:
                        units.extend(workbook_parser.units_from_page_layout(page_row["layout_json"]))
                plan.units = units
                plan.pages = []
                report.sources_rechunked.append(plan.source_path)

        # ---- build chunk candidates and diff against existing rows ----
        source_diffs: dict[str, dict] = {}

        for plan in plans:
            groups = chunking.group_units(plan.units, max_chars=options.max_chunk_chars)
            candidates = chunking.build_chunk_candidates(
                groups,
                source_type=plan.source_type,
                normalisation_version=options.normalisation_version,
            )
            existing_rows = conn.execute(
                "SELECT * FROM chunks WHERE source_pk = ?", (plan.source_pk,)
            ).fetchall()
            matched, to_delete_ids, new_candidates = _match_chunks(existing_rows, candidates)

            diff = {
                "matched": [],
                "to_delete_ids": to_delete_ids,
                "new": [],
            }
            for row, candidate in matched:
                hash_changed = row["semantic_input_hash"] != candidate.semantic_input_hash
                diff["matched"].append((row["chunk_id"], candidate, hash_changed))
                if hash_changed or options.reembed:
                    pending_embeddings[candidate.semantic_input_hash] = candidate.body
            for candidate in new_candidates:
                diff["new"].append(candidate)
                pending_embeddings[candidate.semantic_input_hash] = candidate.body

            source_diffs[plan.source_path] = diff

        # skip hashes already cached for the active model, unless forcing re-embed
        if pending_embeddings and not options.reembed:
            placeholders = ",".join("?" for _ in pending_embeddings)
            cached_rows = conn.execute(
                f"SELECT semantic_input_hash FROM embeddings WHERE model_id = ? "
                f"AND semantic_input_hash IN ({placeholders})",
                (options.model_id, *pending_embeddings.keys()),
            ).fetchall()
            for row in cached_rows:
                pending_embeddings.pop(row["semantic_input_hash"], None)

        missing_hashes = list(pending_embeddings)
        missing_texts = [pending_embeddings[h] for h in missing_hashes]
        vectors = embedder.embed(missing_texts) if missing_texts else []
        _validate_embedding_dimensions(vectors, options.embedding_dimensions)
        hash_to_vector = dict(zip(missing_hashes, vectors))
        report.embeddings_generated = len(missing_hashes)

        # ---- recheck: abort if any selected source changed mid-flight ----
        if any(
            not _source_matches(abs_path, (file_hash, size_bytes, mtime_ns))
            for abs_path, file_hash, size_bytes, mtime_ns in observed_states.values()
        ):
            return SyncReport(status="aborted-source-changed")

        nothing_to_do = (
            not plans
            and not hint_updates
            and not renames
            and not reembed_only_chunks
            and not active_config_changed
        )
        if nothing_to_do:
            return report

        generation = uuid.uuid4().hex
        rendered_assets: dict[str, list] = {}
        asset_generations: dict[str, AssetGeneration] = {}
        generation_root = _asset_generation_root(database_path, generation)
        try:
            for plan in plans:
                if plan.action in ("add", "reparse") and plan.source_type == "pdf" and options.generate_assets:
                    asset_generation, assets = _render_assets(database_path, plan, generation)
                    asset_generations[plan.source_path] = asset_generation
                    rendered_assets[plan.source_path] = assets
        except Exception:
            shutil.rmtree(generation_root, ignore_errors=True)
            raise

        # ==== single write transaction ====
        _asset_event("begin-immediate")
        for abs_path, expected_hash, expected_size, expected_mtime in rename_rechecks.values():
            captured = _capture_stable_file_state(abs_path)
            if captured is None:
                shutil.rmtree(generation_root, ignore_errors=True)
                return SyncReport(status="aborted-source-changed")
            file_hash, size_bytes, mtime_ns = captured
            _asset_event("rename-final-state-captured")
            if (file_hash, size_bytes, mtime_ns) != (expected_hash, expected_size, expected_mtime):
                shutil.rmtree(generation_root, ignore_errors=True)
                return SyncReport(status="aborted-source-changed")
            if not _source_matches(abs_path, (expected_hash, expected_size, expected_mtime)):
                shutil.rmtree(generation_root, ignore_errors=True)
                return SyncReport(status="aborted-source-changed")
        if any(
            not _source_matches(abs_path, (file_hash, size_bytes, mtime_ns))
            for abs_path, file_hash, size_bytes, mtime_ns in observed_states.values()
        ):
            shutil.rmtree(generation_root, ignore_errors=True)
            return SyncReport(status="aborted-source-changed")
        conn.execute("BEGIN IMMEDIATE")
        try:
            backend = vector_backend.SqliteVecBackend()

            # path/mtime hint-only updates for sources whose content, parser,
            # chunker, and normalisation metadata are all unchanged
            for source_path, relative_path, size_bytes, mtime_ns in hint_updates:
                conn.execute(
                    "UPDATE sources SET path = ?, size_bytes = ?, mtime_ns = ? WHERE path = ?",
                    (relative_path, size_bytes, mtime_ns, source_path),
                )

            # renames: relabel path while retaining internal source_pk
            for old_id, new_id in sorted(renames.items()):
                new_relative_path = manifest[new_id]
                _, _, size_bytes, mtime_ns = rename_rechecks[new_id]
                conn.execute(
                    "UPDATE sources SET path = ?, size_bytes = ?, mtime_ns = ? WHERE path = ?",
                    (new_relative_path, size_bytes, mtime_ns, old_id),
                )
                report.sources_renamed.append((old_id, new_id))

            # apply per-plan chunk/page/source changes
            for plan in plans:
                diff = source_diffs[plan.source_path]

                # A brand-new source's row must exist before any chunk that
                # references it via a foreign key is inserted.
                if plan.action == "add":
                    conn.execute(
                        """
                        INSERT INTO sources (
                            path, source_type, language, canonical_url,
                            capture_manifest_ref, sha256, size_bytes, mtime_ns,
                            parser_name, parser_version, parser_config,
                            chunker_name, chunker_version, chunker_config,
                            normalisation_version, normalisation_config,
                            indexed_at_utc, index_status
                        ) VALUES (?, ?, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok')
                        """,
                        (
                            plan.relative_path,
                            plan.source_type,
                            plan.sha256,
                            plan.size_bytes,
                            plan.mtime_ns,
                            options.parser_name(plan.source_type),
                            options.parser_version(plan.source_type),
                            json.dumps(plan.parser_config),
                            schema.CHUNKER_NAME,
                            options.chunker_version,
                            json.dumps(plan.chunker_config),
                            options.normalisation_version,
                            json.dumps(plan.normalisation_config),
                            schema.utc_now(),
                        ),
                    )
                    plan.source_pk = conn.execute(
                        "SELECT source_pk FROM sources WHERE path = ?", (plan.relative_path,)
                    ).fetchone()["source_pk"]
                    asset_generation = asset_generations.get(plan.source_path)
                    if asset_generation is not None:
                        path_mapping = asset_generation.finalize_new_source(plan.source_pk)
                        rendered_assets[plan.source_path] = [
                            (physical_page, path_mapping.get(asset_path, asset_path), render, asset_type, sha256)
                            for physical_page, asset_path, render, asset_type, sha256 in rendered_assets.get(plan.source_path, [])
                        ]
                    assert plan.source_pk is not None

                for chunk_id in diff["to_delete_ids"]:
                    conn.execute("DELETE FROM chunks WHERE chunk_id = ?", (chunk_id,))
                    report.chunks_deleted += 1

                for chunk_id, candidate, hash_changed in diff["matched"]:
                    conn.execute(
                        """
                        UPDATE chunks SET
                            logical_key = ?, ordinal = ?, heading_path = ?, symbol = ?,
                            body = ?, semantic_input_hash = ?, lexical_hash = ?,
                            content_type = ?, physical_page = ?, page_start_offset = ?,
                            page_end_offset = ?, page_range_start = ?, page_range_end = ?,
                            line_start = ?, line_end = ?, locator_json = ?
                        WHERE chunk_id = ?
                        """,
                        (
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
                            chunk_id,
                        ),
                    )
                    report.chunks_updated += 1
                    if hash_changed or options.reembed:
                        embedding_id = _ensure_embedding(
                            conn, backend, options.model_id, candidate.semantic_input_hash, hash_to_vector
                        )
                        conn.execute(
                            "DELETE FROM chunk_embeddings WHERE chunk_id = ?", (chunk_id,)
                        )
                        conn.execute(
                            "INSERT OR IGNORE INTO chunk_embeddings(chunk_id, embedding_id) VALUES (?, ?)",
                            (chunk_id, embedding_id),
                        )

                for candidate in diff["new"]:
                    chunk_id = uuid.uuid4().hex
                    conn.execute(
                        """
                        INSERT INTO chunks (
                            chunk_id, source_pk, logical_key, ordinal, heading_path, symbol,
                            body, semantic_input_hash, lexical_hash, content_type,
                            physical_page, page_start_offset, page_end_offset,
                            page_range_start, page_range_end, line_start, line_end, locator_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            chunk_id,
                            plan.source_pk,
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
                        ),
                    )
                    report.chunks_added += 1
                    embedding_id = _ensure_embedding(
                        conn, backend, options.model_id, candidate.semantic_input_hash, hash_to_vector
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO chunk_embeddings(chunk_id, embedding_id) VALUES (?, ?)",
                        (chunk_id, embedding_id),
                    )

                # pages + source metadata for add/reparse; assets regenerated only then
                if plan.action in ("add", "reparse"):
                    conn.execute("DELETE FROM pages WHERE source_pk = ?", (plan.source_pk,))
                    for page in plan.pages:
                        conn.execute(
                            """
                            INSERT INTO pages (
                                source_pk, physical_page, printed_label, text,
                                extraction_method, extraction_status, section_candidates, layout_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                plan.source_pk,
                                page.physical_page,
                                page.printed_label,
                                page.text,
                                page.extraction_method,
                                page.extraction_status,
                                json.dumps(page.section_candidates),
                                json.dumps(page.layout) if page.layout is not None else None,
                            ),
                        )

                    if plan.action == "reparse":
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
                            (
                                plan.relative_path,
                                plan.sha256,
                                plan.size_bytes,
                                plan.mtime_ns,
                                options.parser_name(plan.source_type),
                                options.parser_version(plan.source_type),
                                json.dumps(plan.parser_config),
                                schema.CHUNKER_NAME,
                                options.chunker_version,
                                json.dumps(plan.chunker_config),
                                options.normalisation_version,
                                json.dumps(plan.normalisation_config),
                                schema.utc_now(),
                                plan.source_pk,
                            ),
                        )

                    if plan.source_type == "pdf" and options.generate_assets:
                        _persist_assets(conn, plan, rendered_assets.get(plan.source_path, []), database_path)
                else:
                    conn.execute(
                        """
                        UPDATE sources SET
                            chunker_name = ?, chunker_version = ?, chunker_config = ?,
                            normalisation_version = ?, normalisation_config = ?,
                            indexed_at_utc = ?, index_status = 'ok'
                        WHERE source_pk = ?
                        """,
                        (
                            schema.CHUNKER_NAME,
                            options.chunker_version,
                            json.dumps(plan.chunker_config),
                            options.normalisation_version,
                            json.dumps(plan.normalisation_config),
                            schema.utc_now(),
                            plan.source_pk,
                        ),
                    )

            # top up embeddings for otherwise-untouched sources whose only
            # invalidation is a changed active embedding model
            for chunk_id, semantic_input_hash in reembed_only_chunks:
                embedding_id = _ensure_embedding(
                    conn, backend, options.model_id, semantic_input_hash, hash_to_vector
                )
                conn.execute(
                    "INSERT OR IGNORE INTO chunk_embeddings(chunk_id, embedding_id) VALUES (?, ?)",
                    (chunk_id, embedding_id),
                )

            _asset_event("pre-commit-source-check")
            if any(
                not _source_matches(abs_path, (file_hash, size_bytes, mtime_ns))
                for abs_path, file_hash, size_bytes, mtime_ns in observed_states.values()
            ):
                raise _SourceChangedDuringSync

            schema.touch_config(conn)
            schema.activate_embedding_config(
                conn,
                embedding_model=options.embedding_model,
                embedding_revision=options.embedding_revision,
                embedding_dimensions=options.embedding_dimensions,
            )
            conn.execute("COMMIT")
        except _SourceChangedDuringSync:
            try:
                if getattr(conn, "in_transaction", True):
                    conn.execute("ROLLBACK")
            finally:
                shutil.rmtree(generation_root, ignore_errors=True)
            return SyncReport(status="aborted-source-changed")
        except Exception:
            try:
                if getattr(conn, "in_transaction", True):
                    conn.execute("ROLLBACK")
            except Exception:
                pass
            shutil.rmtree(generation_root, ignore_errors=True)
            raise

        if options.cleanup_asset_generations:
            report.cleanup_warnings.extend(cleanup_asset_generations(conn, database_path))

        return report
    finally:
        conn.close()
        if snapshot_root is not None:
            shutil.rmtree(snapshot_root, ignore_errors=True)


def plan_prune(conn: sqlite3.Connection, selected_paths: Collection[str]) -> PrunePlan:
    rows = conn.execute("SELECT path FROM sources ORDER BY path").fetchall()
    selected = set(selected_paths)
    return PrunePlan(tuple(row["path"] for row in rows if row["path"] not in selected))


def validate_prune_plan(conn: sqlite3.Connection, database_path: Path, plan: PrunePlan) -> None:
    _validated_prune_asset_targets(conn, database_path, plan)


def _canonical_asset_parts(database_path: Path, stored_asset_path: str, *, validate_filesystem: bool = True) -> tuple[str, ...]:
    if validate_filesystem:
        resolved = schema.resolve_asset_path(database_path, stored_asset_path)
    elif stored_asset_path.startswith("/"):
        resolved = Path(stored_asset_path)
    else:
        resolved = Path(database_path).resolve().parent.joinpath(*stored_asset_path.split("/"))
    try:
        relative = resolved.relative_to(Path(database_path).resolve().parent)
    except ValueError as exc:
        raise ValueError(f"asset identifier escapes database asset root: {stored_asset_path!r}") from exc
    return relative.parts


def _prune_asset_target(
    database_path: Path, source_pk: int, stored_asset_path: str, *, validate_filesystem: bool = True
) -> _PruneAssetTarget:
    parts = _canonical_asset_parts(database_path, stored_asset_path, validate_filesystem=validate_filesystem)
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
    source_dir = schema.imgs_dir(database_path) / "generations" / generation / stored_source_pk
    return _PruneAssetTarget(generation=generation, source_pk=source_pk, source_dir=source_dir)


def _validated_prune_asset_targets(conn: sqlite3.Connection, database_path: Path, plan: PrunePlan) -> set[_PruneAssetTarget]:
    targets: set[_PruneAssetTarget] = set()
    targets_by_source: dict[int, set[_PruneAssetTarget]] = defaultdict(set)
    for path in plan.paths:
        row = conn.execute("SELECT source_pk FROM sources WHERE path = ?", (path,)).fetchone()
        if row is None:
            continue
        source_pk = row["source_pk"]
        asset_rows = conn.execute("SELECT asset_path FROM assets WHERE source_pk = ?", (row["source_pk"],)).fetchall()
        for asset_row in asset_rows:
            target = _prune_asset_target(database_path, source_pk, asset_row["asset_path"])
            targets.add(target)
            targets_by_source[source_pk].add(target)
    for source_pk, source_targets in targets_by_source.items():
        if len(source_targets) > 1:
            raise ValueError(f"asset identifiers for source_pk {source_pk} span multiple generation/source directories")
    return targets


def _require_dirfd_primitives() -> None:
    required = (os.open, os.stat, os.unlink, os.rename, os.rmdir)
    if not all(func in os.supports_dir_fd for func in required):
        raise OSError("safe asset cleanup requires POSIX dir_fd support")
    if os.stat not in os.supports_follow_symlinks:
        raise OSError("safe asset cleanup requires no-follow stat support")
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise OSError("safe asset cleanup requires O_DIRECTORY and O_NOFOLLOW")


def _open_dir_at(parent_fd: int, name: str) -> int:
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)


def _unlink_symlink_at(parent_fd: int, name: str) -> bool:
    try:
        mode = os.stat(name, dir_fd=parent_fd, follow_symlinks=False).st_mode
    except FileNotFoundError:
        return True
    if stat.S_ISLNK(mode):
        os.unlink(name, dir_fd=parent_fd)
        return True
    return False


def _rmtree_dir_at(parent_fd: int, name: str) -> None:
    child_fd = _open_dir_at(parent_fd, name)
    try:
        for entry in os.listdir(child_fd):
            mode = os.stat(entry, dir_fd=child_fd, follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
                _rmtree_dir_at(child_fd, entry)
            else:
                os.unlink(entry, dir_fd=child_fd)
    finally:
        os.close(child_fd)
    os.rmdir(name, dir_fd=parent_fd)


def _quarantine_fd_at(generations_fd: int) -> int:
    quarantine_root = ".prune-quarantine"
    try:
        os.mkdir(quarantine_root, dir_fd=generations_fd)
    except FileExistsError:
        pass
    try:
        return _open_dir_at(generations_fd, quarantine_root)
    except OSError:
        if _unlink_symlink_at(generations_fd, quarantine_root):
            os.mkdir(quarantine_root, dir_fd=generations_fd)
            return _open_dir_at(generations_fd, quarantine_root)
        raise


def _remove_generation_entry_at(generations_fd: int, generation: str) -> None:
    try:
        generation_fd = _open_dir_at(generations_fd, generation)
    except FileNotFoundError:
        return
    except OSError:
        if _unlink_symlink_at(generations_fd, generation):
            return
        raise
    else:
        os.close(generation_fd)

    quarantine_fd = _quarantine_fd_at(generations_fd)
    quarantine_name = f"{generation}-{uuid.uuid4().hex}"
    try:
        os.rename(generation, quarantine_name, src_dir_fd=generations_fd, dst_dir_fd=quarantine_fd)
        try:
            mode = os.stat(quarantine_name, dir_fd=quarantine_fd, follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode):
                os.unlink(quarantine_name, dir_fd=quarantine_fd)
            elif stat.S_ISDIR(mode):
                _rmtree_dir_at(quarantine_fd, quarantine_name)
            else:
                raise ValueError(f"quarantined asset generation is not a directory: {generation}")
        except Exception:
            try:
                os.rename(quarantine_name, generation, src_dir_fd=quarantine_fd, dst_dir_fd=generations_fd)
            except Exception:
                pass
            raise
    finally:
        os.close(quarantine_fd)
    try:
        os.rmdir(".prune-quarantine", dir_fd=generations_fd)
    except OSError:
        pass


def _remove_source_entry_at(generations_fd: int, generation: str, source_pk: str, source_dir: Path) -> None:
    try:
        generation_fd = _open_dir_at(generations_fd, generation)
    except FileNotFoundError:
        return
    except OSError:
        if _unlink_symlink_at(generations_fd, generation):
            return
        raise
    try:
        try:
            mode = os.stat(source_pk, dir_fd=generation_fd, follow_symlinks=False).st_mode
        except FileNotFoundError:
            return
        if stat.S_ISLNK(mode):
            os.unlink(source_pk, dir_fd=generation_fd)
            return
        if not stat.S_ISDIR(mode):
            raise ValueError(f"pruned asset path is not a directory: {source_dir}")
        quarantine_fd = _quarantine_fd_at(generations_fd)
        quarantine_name = f"{generation}-{source_pk}-{uuid.uuid4().hex}"
        try:
            os.rename(source_pk, quarantine_name, src_dir_fd=generation_fd, dst_dir_fd=quarantine_fd)
            try:
                mode = os.stat(quarantine_name, dir_fd=quarantine_fd, follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    os.unlink(quarantine_name, dir_fd=quarantine_fd)
                elif stat.S_ISDIR(mode):
                    _rmtree_dir_at(quarantine_fd, quarantine_name)
                else:
                    raise ValueError(f"quarantined asset path is not a directory: {source_dir}")
            except Exception:
                try:
                    os.rename(quarantine_name, source_pk, src_dir_fd=quarantine_fd, dst_dir_fd=generation_fd)
                except Exception:
                    pass
                raise
        finally:
            os.close(quarantine_fd)
        try:
            os.rmdir(".prune-quarantine", dir_fd=generations_fd)
        except OSError:
            pass
    finally:
        os.close(generation_fd)


def _with_generations_fd(database_path: Path, action) -> None:
    _require_dirfd_primitives()
    database_parent = Path(database_path).resolve().parent
    parent_fd = os.open(database_parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        imgs_fd = _open_dir_at(parent_fd, "imgs")
        try:
            generations_fd = _open_dir_at(imgs_fd, "generations")
            try:
                action(generations_fd)
            finally:
                os.close(generations_fd)
        finally:
            os.close(imgs_fd)
    finally:
        os.close(parent_fd)


def _safe_remove_asset_generation(database_path: Path, generation_dir: Path) -> None:
    database_parent = Path(database_path).resolve().parent
    generations_root = database_parent / "imgs" / "generations"
    generation_dir = Path(generation_dir)
    try:
        generation = generation_dir.relative_to(generations_root).parts
    except ValueError as exc:
        raise ValueError(f"asset generation escapes image root: {generation_dir}") from exc
    if len(generation) != 1:
        raise ValueError(f"asset generation cleanup expects a generation directory: {generation_dir}")

    def action(generations_fd: int) -> None:
        _remove_generation_entry_at(generations_fd, generation[0])

    _with_generations_fd(database_path, action)


def _safe_remove_pruned_asset_dir(source_dir: Path, database_path: Path) -> None:
    database_parent = Path(database_path).resolve().parent
    generations_root = database_parent / "imgs" / "generations"
    source_dir = Path(source_dir)
    try:
        source_dir.relative_to(generations_root)
    except ValueError as exc:
        raise ValueError(f"pruned asset directory escapes image root: {source_dir}") from exc

    relative_parts = source_dir.relative_to(generations_root).parts
    if len(relative_parts) != 2:
        raise ValueError(f"pruned asset directory must be a generation/source directory: {source_dir}")
    generation, source_pk = relative_parts

    def action(generations_fd: int) -> None:
        _remove_source_entry_at(generations_fd, generation, source_pk, source_dir)

    _with_generations_fd(database_path, action)


def apply_prune(conn: sqlite3.Connection, database_path: Path, plan: PrunePlan) -> list[str]:
    backend = vector_backend.SqliteVecBackend()
    _validated_prune_asset_targets(conn, database_path, plan)
    conn.execute("BEGIN IMMEDIATE")
    try:
        pruned_asset_targets = _validated_prune_asset_targets(conn, database_path, plan)
        for path in plan.paths:
            row = conn.execute("SELECT source_pk FROM sources WHERE path = ?", (path,)).fetchone()
            if row is None:
                continue
            conn.execute("DELETE FROM sources WHERE source_pk = ?", (row["source_pk"],))
        orphan_rows = conn.execute(
            "SELECT embedding_id FROM embeddings WHERE embedding_id NOT IN (SELECT embedding_id FROM chunk_embeddings)"
        ).fetchall()
        for row in orphan_rows:
            backend.delete(conn, row["embedding_id"])
            conn.execute("DELETE FROM embeddings WHERE embedding_id = ?", (row["embedding_id"],))
        schema.touch_config(conn)
        conn.execute("COMMIT")
    except Exception:
        try:
            if getattr(conn, "in_transaction", True):
                conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    leaks: list[str] = []
    referenced_dirs = {
        _prune_asset_target(database_path, row["source_pk"], row["asset_path"], validate_filesystem=False).source_dir
        for row in conn.execute("SELECT source_pk, asset_path FROM assets").fetchall()
    }
    for target in sorted(pruned_asset_targets, key=lambda item: str(item.source_dir)):
        asset_dir = target.source_dir
        if asset_dir in referenced_dirs:
            continue
        try:
            _safe_remove_pruned_asset_dir(asset_dir, database_path)
        except Exception as exc:
            leaks.append(f"failed to remove pruned asset directory {asset_dir}: {exc}")
    try:
        leaks.extend(cleanup_asset_generations(conn, database_path))
    except Exception as exc:
        leaks.append(f"failed to clean unreferenced asset generations: {exc}")
    return leaks


def _ensure_embedding(
    conn: sqlite3.Connection,
    backend: vector_backend.SqliteVecBackend,
    model_id: str,
    semantic_input_hash: str,
    hash_to_vector: dict[str, list[float]],
) -> int:
    row = conn.execute(
        "SELECT embedding_id FROM embeddings WHERE model_id = ? AND semantic_input_hash = ?",
        (model_id, semantic_input_hash),
    ).fetchone()
    vector = hash_to_vector.get(semantic_input_hash)
    if row is not None:
        if vector is not None:
            backend.upsert(conn, row["embedding_id"], vector)
        return row["embedding_id"]

    if vector is None:
        raise SyncError(
            f"no embedding available for semantic_input_hash={semantic_input_hash!r}; "
            "this indicates a bug in the pending-embedding queue"
        )
    cursor = conn.execute(
        "INSERT INTO embeddings(model_id, semantic_input_hash, created_at_utc) VALUES (?, ?, ?)",
        (model_id, semantic_input_hash, schema.utc_now()),
    )
    embedding_id = cursor.lastrowid
    backend.upsert(conn, embedding_id, vector)
    return embedding_id


def _asset_generation_root(database_path: Path, generation: str) -> Path:
    return schema.resolve_asset_path(database_path, f"imgs/generations/{generation}")


def _render_assets(database_path: Path, plan: _SourcePlan, generation: str) -> tuple[AssetGeneration, list[tuple[int, Path, object, str]]]:
    generation_root = _asset_generation_root(database_path, generation)
    staging_dir = None
    if plan.source_pk is None:
        base_dir = generation_root / f".staging-{uuid.uuid4().hex}"
        staging_dir = base_dir
    else:
        base_dir = generation_root / str(plan.source_pk)
    base_dir.mkdir(parents=True, exist_ok=False)
    rendered = []
    physical_pages = sorted({page.physical_page for page in plan.pages})
    for physical_page in physical_pages:
        render = pdf_parser.render_page(plan.content_path, physical_page)
        asset_path = base_dir / f"page-{physical_page:04d}.{render.ext}"
        asset_path.write_bytes(render.image_bytes)
        sha256 = hashlib.sha256(asset_path.read_bytes()).hexdigest()
        _asset_event("asset-hash")
        rendered.append((physical_page, asset_path, render, "page-render", sha256))
        for crop in pdf_parser.render_figure_crops(plan.content_path, physical_page):
            crop_path = base_dir / f"{crop.label}.{crop.ext}"
            crop_path.write_bytes(crop.image_bytes)
            sha256 = hashlib.sha256(crop_path.read_bytes()).hexdigest()
            _asset_event("asset-hash")
            rendered.append((physical_page, crop_path, crop, "figure-crop", sha256))
    generation_obj = AssetGeneration(
        generation_id=generation,
        root=generation_root,
        referenced_files=tuple(path for _, path, _, _, _ in rendered),
        staging_dir=staging_dir,
    )
    return generation_obj, rendered


def _persist_assets(conn: sqlite3.Connection, plan: _SourcePlan, rendered_assets, database_path: Path) -> None:
    assert plan.source_pk is not None
    conn.execute("DELETE FROM assets WHERE source_pk = ?", (plan.source_pk,))
    for physical_page, asset_path, render, asset_type, sha256 in rendered_assets:
        _insert_asset(conn, plan.source_pk, plan.source_path, physical_page, asset_path, render, asset_type, sha256, database_path)


def referenced_asset_generations(conn: sqlite3.Connection, database_path: Path | None = None) -> set[Path]:
    rows = conn.execute("SELECT asset_path FROM assets").fetchall()
    if database_path is None:
        database_path_row = conn.execute("PRAGMA database_list").fetchone()
        database_path = Path(database_path_row["file"]) if database_path_row is not None and database_path_row["file"] else None
    if database_path is None:
        return {Path(row["asset_path"]).parents[1] for row in rows}
    database_parent = Path(database_path).resolve().parent
    referenced: set[Path] = set()
    for row in rows:
        parts = _canonical_asset_parts(
            database_path,
            row["asset_path"],
            validate_filesystem=False,
        )
        if len(parts) < 3 or parts[:2] != ("imgs", "generations"):
            raise ValueError(f"asset identifier has the wrong generation root: {row['asset_path']!r}")
        referenced.add(database_parent.joinpath(*parts[:3]))
    return referenced


def cleanup_asset_generations(conn: sqlite3.Connection, database_path: Path) -> list[str]:
    leaks: list[str] = []
    root = schema.imgs_dir(database_path) / "generations"
    if not root.exists():
        return leaks
    referenced = referenced_asset_generations(conn, database_path)
    for generation in root.iterdir():
        if generation.name == ".prune-quarantine":
            continue
        if generation.is_symlink():
            try:
                _safe_remove_asset_generation(database_path, generation)
            except Exception as exc:
                leaks.append(f"failed to remove invalid asset generation symlink {generation}: {exc}")
            continue
        if generation not in referenced:
            try:
                _safe_remove_asset_generation(database_path, generation)
            except Exception as exc:
                leaks.append(f"failed to remove unreferenced asset generation {generation}: {exc}")
    return leaks


def _insert_asset(conn, source_pk: int, source_path: str, physical_page, asset_path: Path, render, asset_type: str, sha256: str, database_path: Path) -> None:
    asset_id = f"{source_path}:{asset_path.stem}"
    asset_identifier = asset_path.resolve().relative_to(Path(database_path).resolve().parent).as_posix()
    schema.resolve_asset_path(database_path, asset_identifier)
    # `ocr_text`/`visual_description` remain hardcoded NULL -- out of scope
    # for this change (task 0090 item 1/2 boundary: OCR fallback targets
    # page/chunk text only, not the assets table's separate OCR/visual
    # description columns).
    conn.execute(
        """
        INSERT INTO assets (
            asset_id, source_pk, physical_page, asset_path, sha256, width, height,
            asset_type, label, caption, nearby_text, ocr_text, visual_description, bbox_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, ?)
        """,
        (
            asset_id,
            source_pk,
            physical_page,
            asset_identifier,
            sha256,
            render.width,
            render.height,
            asset_type,
            render.label,
            render.nearby_text,
            json.dumps(render.bbox) if render.bbox else None,
        ),
    )


def integrity_check(conn: sqlite3.Connection) -> list[str]:
    issues: list[str] = []
    database_path_row = conn.execute("PRAGMA database_list").fetchone()
    database_path = Path(database_path_row["file"]) if database_path_row is not None and database_path_row["file"] else None

    fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    chunks_count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    if fts_count != chunks_count:
        issues.append(f"chunks_fts has {fts_count} rows but chunks has {chunks_count} rows")

    orphan_chunk_embeddings = conn.execute(
        """
        SELECT ce.chunk_id FROM chunk_embeddings ce
        LEFT JOIN chunks c ON c.chunk_id = ce.chunk_id
        WHERE c.chunk_id IS NULL
        """
    ).fetchall()
    for row in orphan_chunk_embeddings:
        issues.append(f"chunk_embeddings references missing chunk {row['chunk_id']}")

    backend = vector_backend.SqliteVecBackend()
    issues.extend(backend.integrity_check(conn))

    missing_assets = conn.execute("SELECT asset_id, asset_path FROM assets").fetchall()
    for row in missing_assets:
        asset_path = schema.resolve_asset_path(database_path, row["asset_path"]) if database_path is not None else Path(row["asset_path"])
        if not asset_path.is_file():
            issues.append(f"asset {row['asset_id']} references missing file {row['asset_path']}")
            continue
        expected = conn.execute("SELECT sha256 FROM assets WHERE asset_id = ?", (row["asset_id"],)).fetchone()["sha256"]
        actual = hashlib.sha256(asset_path.read_bytes()).hexdigest()
        if actual != expected:
            issues.append(f"asset {row['asset_id']} hash mismatch: expected {expected}, got {actual}")

    return issues
