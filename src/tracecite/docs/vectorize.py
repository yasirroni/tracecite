"""Adapter that feeds retained documentation into the existing evidence stack."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import TYPE_CHECKING

from ..tables import augment_document_with_embedding_text
from .contract import DocsEvidenceContract
from .stage import validate_retained_source_links

if TYPE_CHECKING:
    from ..evidence.sync import SyncOptions, SyncReport

INDEX_INPUT_NAME = "index-input"
MANIFEST_NAME = "index-input.manifest.toml"

_EXCLUDED_DIR_NAMES = {
    ".git",
    ".quarto",
    "_quarto",
    "_site",
    "site_libs",
    "_tracecite",
    ".tracecite",
    "build",
    ".pytest_cache",
    ".venv",
    "dist",
    "__pycache__",
    "model-cache",
}
_EXCLUDED_SUFFIXES = {".html"}
_RESOURCE_REFERENCE_RE = re.compile(
    r"(?:!\[[^\]]*\]|\[[^\]]*\])\(([^)]+)\)|^\s*\[[^\]]+\]:\s*(\S+)",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class DocsIndexProfile:
    input_root: Path
    manifest_path: Path
    database_path: Path
    model_cache_dir: Path


@dataclass(frozen=True, slots=True)
class DocsIndexResult:
    profile: DocsIndexProfile
    tables_normalized: int
    sync_report: SyncReport


def resolve_docs_index_profile(contract: DocsEvidenceContract) -> DocsIndexProfile:
    database_path = contract.index_output.resolve()
    return DocsIndexProfile(
        input_root=(contract.staged_root / INDEX_INPUT_NAME).resolve(),
        manifest_path=(contract.staged_root / MANIFEST_NAME).resolve(),
        database_path=database_path,
        model_cache_dir=(database_path.parent / "model-cache").resolve(),
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_publication_excluded(path: Path, contract: DocsEvidenceContract) -> bool:
    resolved = path.resolve()
    for exclude in contract.publication_exclude:
        target = exclude.resolve()
        if resolved == target:
            return True
        if target.is_dir() and _inside(resolved, target):
            return True
    return False


def _should_skip_retained_path(path: Path, retained_root: Path) -> bool:
    if not path.is_file():
        return True
    relative = path.relative_to(retained_root)
    if any(part in _EXCLUDED_DIR_NAMES or part.startswith(".tracecite") for part in relative.parts):
        return True
    if path.suffix.lower() in _EXCLUDED_SUFFIXES:
        return True
    if path.name.endswith("_files"):
        return True
    return False


def _mirror_exclude_globs(contract: DocsEvidenceContract, repo_root: Path) -> tuple[str, ...]:
    retained = contract.retained_root.resolve()
    globs: set[str] = set()
    for exclude in contract.publication_exclude:
        target = exclude.resolve()
        if not _inside(target, retained):
            continue
        relative = target.relative_to(retained).as_posix()
        if not relative or relative == ".":
            raise ValueError(f"publication_exclude cannot exclude the entire retained root: {exclude}")
        if ".." in relative.split("/"):
            raise ValueError(f"publication_exclude cannot be represented safely in the mirror: {exclude}")
        globs.add(f"{relative}/**" if target.is_dir() else relative)
    for name in sorted(_EXCLUDED_DIR_NAMES):
        globs.add(f"**/{name}/**")
    for suffix in sorted(_EXCLUDED_SUFFIXES):
        globs.add(f"**/*{suffix}")
    globs.add("**/*_files/**")
    return tuple(sorted(globs))


def _retained_markdown_paths(contract: DocsEvidenceContract) -> list[Path]:
    retained = contract.retained_root.resolve()
    paths = [
        path
        for path in sorted(retained.rglob("*.md"))
        if not _should_skip_retained_path(path, retained) and not _is_publication_excluded(path, contract)
    ]
    return paths


def _local_resource_destinations(markdown: str) -> set[str]:
    destinations: set[str] = set()
    for match in _RESOURCE_REFERENCE_RE.finditer(markdown):
        destination = (match.group(1) or match.group(2) or "").strip()
        if not destination or destination.startswith("<"):
            continue
        lowered = destination.lower()
        if lowered.startswith(("http://", "https://", "mailto:")):
            continue
        if "#page=" in lowered or lowered.endswith(".pdf"):
            continue
        destination = destination.split("#", 1)[0].strip()
        if destination:
            destinations.add(destination)
    return destinations


def _copy_resource_files(
    *,
    source_markdown: Path,
    retained_root: Path,
    mirror_root: Path,
    original_markdown: str,
) -> None:
    for destination in sorted(_local_resource_destinations(original_markdown)):
        source = (source_markdown.parent / destination).resolve()
        if not source.is_file() or not _inside(source, retained_root):
            continue
        target = mirror_root / source.relative_to(retained_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _render_manifest(exclude_globs: tuple[str, ...]) -> str:
    lines = ["schema_version = 1", "", "[[include]]", 'glob = "**/*.md"']
    for pattern in exclude_globs:
        lines.extend(["", "[[exclude]]", f'glob = "{pattern}"'])
    return "\n".join(lines) + "\n"


def _snapshot_retained(retained_root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(retained_root): path.read_bytes()
        for path in sorted(retained_root.rglob("*"))
        if path.is_file()
    }


def _assert_retained_unchanged(retained_root: Path, before: dict[Path, bytes]) -> None:
    after = _snapshot_retained(retained_root)
    if before != after:
        changed = sorted(set(before) ^ set(after) | {path for path in before if before.get(path) != after.get(path)})
        raise RuntimeError(f"retained Markdown was mutated during index-input preparation: {changed[0]}")


def _atomic_promote_pair(replacements: tuple[tuple[Path, Path], ...]) -> None:
    """Replace every destination with its staged temp path, or roll all of them back.

    ``replacements`` is a sequence of ``(temp_path, destination)`` pairs. If any
    individual replace fails partway through, every destination already moved is
    restored to its prior content and no stray ``.previous`` backup is left behind.
    """
    backups: list[tuple[Path, Path]] = []
    try:
        for _temp, destination in replacements:
            if destination.exists():
                backup = destination.with_name(f".{destination.name}.previous")
                if backup.exists():
                    shutil.rmtree(backup) if backup.is_dir() else backup.unlink()
                os.replace(destination, backup)
                backups.append((destination, backup))
        for temp, destination in replacements:
            os.replace(temp, destination)
    except Exception:
        for _temp, destination in replacements:
            if destination.exists():
                shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
        for destination, backup in backups:
            os.replace(backup, destination)
        raise
    else:
        for _destination, backup in backups:
            if backup.exists():
                shutil.rmtree(backup) if backup.is_dir() else backup.unlink()


def prepare_docs_index_input(
    contract: DocsEvidenceContract,
    *,
    repo_root: str | Path,
    strict_tables: bool = False,
    pandoc: str | Path | None = None,
    allow_pipe_fallback: bool = False,
) -> DocsIndexProfile:
    profile, _tables = _prepare_docs_index_input(
        contract,
        repo_root=repo_root,
        strict_tables=strict_tables,
        pandoc=pandoc,
        allow_pipe_fallback=allow_pipe_fallback,
    )
    return profile


def _prepare_docs_index_input(
    contract: DocsEvidenceContract,
    *,
    repo_root: str | Path,
    strict_tables: bool = False,
    pandoc: str | Path | None = None,
    allow_pipe_fallback: bool = False,
) -> tuple[DocsIndexProfile, int]:
    root = Path(repo_root).resolve()
    profile = resolve_docs_index_profile(contract)
    retained = contract.retained_root.resolve()
    before = _snapshot_retained(retained)

    link_issues = validate_retained_source_links(contract, repo_root=root)
    if link_issues:
        raise ValueError("; ".join(link_issues))

    exclude_globs = _mirror_exclude_globs(contract, root)
    manifest_text = _render_manifest(exclude_globs)
    markdown_paths = _retained_markdown_paths(contract)

    contract.staged_root.parent.mkdir(parents=True, exist_ok=True)
    contract.staged_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".index-input-", dir=contract.staged_root.parent))
    temp_input = temporary / INDEX_INPUT_NAME
    temp_manifest = temporary / MANIFEST_NAME
    tables_normalized = 0

    try:
        temp_input.mkdir(parents=True, exist_ok=True)
        for source_path in markdown_paths:
            relative = source_path.relative_to(retained)
            original = source_path.read_text(encoding="utf-8")
            transformed = augment_document_with_embedding_text(
                original,
                document_path=relative.as_posix(),
                strict=strict_tables,
                pandoc=pandoc,
                allow_pipe_fallback=allow_pipe_fallback,
            )
            tables_normalized += len(transformed.tables)
            destination = temp_input / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(transformed.markdown, encoding="utf-8")
            _copy_resource_files(
                source_markdown=source_path,
                retained_root=retained,
                mirror_root=temp_input,
                original_markdown=original,
            )

        temp_manifest.write_text(manifest_text, encoding="utf-8")

        _atomic_promote_pair(
            (
                (temp_input, profile.input_root),
                (temp_manifest, profile.manifest_path),
            )
        )
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
        _assert_retained_unchanged(retained, before)

    return profile, tables_normalized


def sync_docs_index(
    contract: DocsEvidenceContract,
    *,
    repo_root: str | Path,
    options: SyncOptions | None = None,
    embedder=None,
    strict_tables: bool = False,
    pandoc: str | Path | None = None,
    allow_pipe_fallback: bool = False,
) -> DocsIndexResult:
    profile, tables_normalized = _prepare_docs_index_input(
        contract,
        repo_root=repo_root,
        strict_tables=strict_tables,
        pandoc=pandoc,
        allow_pipe_fallback=allow_pipe_fallback,
    )
    from ..evidence import sync as sync_module

    report = sync_module.sync(
        profile.input_root,
        profile.manifest_path,
        profile.database_path,
        options=options,
        embedder=embedder,
        model_cache_dir=profile.model_cache_dir,
    )
    return DocsIndexResult(profile, tables_normalized, report)


def search_docs_index(
    contract: DocsEvidenceContract,
    query: str,
    *,
    repo_root: str | Path,
    limit: int = 10,
    fts_limit: int = 50,
    vector_limit: int = 50,
    embedder=None,
) -> list[dict]:
    del repo_root
    from ..evidence import schema
    from ..evidence.commands import hybrid_search

    profile = resolve_docs_index_profile(contract)
    if not profile.database_path.is_file():
        return []
    conn = schema.connect_existing(profile.database_path, read_only=True)
    try:
        schema.ensure_schema(conn)
        return hybrid_search(
            conn,
            profile.input_root,
            query,
            limit,
            fts_limit,
            vector_limit,
            embedder if embedder is not None else profile.model_cache_dir,
            profile.database_path,
            embedder=embedder,
        )
    finally:
        conn.close()


def _index_input_freshness(contract: DocsEvidenceContract, profile: DocsIndexProfile) -> tuple[str, ...]:
    diagnostics: list[str] = []
    if not profile.input_root.is_dir():
        diagnostics.append("index-input mirror is missing")
        return tuple(diagnostics)
    if not profile.manifest_path.is_file():
        diagnostics.append("index-input manifest is missing")
    expected_paths = {
        path.relative_to(contract.retained_root).as_posix()
        for path in _retained_markdown_paths(contract)
    }
    actual_paths = {
        path.relative_to(profile.input_root).as_posix()
        for path in sorted(profile.input_root.rglob("*.md"))
        if path.is_file()
    }
    for path in sorted(expected_paths - actual_paths):
        diagnostics.append(f"index-input missing: {path}")
    for path in sorted(actual_paths - expected_paths):
        diagnostics.append(f"index-input extra: {path}")
    for relative in sorted(expected_paths & actual_paths):
        source = contract.retained_root / relative
        mirror = profile.input_root / relative
        expected = augment_document_with_embedding_text(
            source.read_text(encoding="utf-8"),
            document_path=relative,
        ).markdown
        if mirror.read_text(encoding="utf-8") != expected:
            diagnostics.append(f"index-input stale (retained changed): {relative}")
    for path in sorted(profile.input_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(profile.input_root)
        if any(part in _EXCLUDED_DIR_NAMES for part in relative.parts):
            diagnostics.append(f"index-input leaked artifact: {relative.as_posix()}")
        if path.suffix.lower() in _EXCLUDED_SUFFIXES:
            diagnostics.append(f"index-input leaked artifact: {relative.as_posix()}")
    return tuple(diagnostics)


def _manifest_freshness(
    contract: DocsEvidenceContract, profile: DocsIndexProfile, repo_root: Path,
) -> tuple[str, ...]:
    if not profile.manifest_path.is_file():
        return ()
    expected = _render_manifest(_mirror_exclude_globs(contract, repo_root))
    try:
        actual = profile.manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        return (f"index-input manifest is unreadable: {exc}",)
    if actual != expected:
        return ("index-input manifest is stale or does not match the current docs contract",)
    return ()


def _database_freshness(profile: DocsIndexProfile) -> tuple[str, ...]:
    if not profile.manifest_path.is_file():
        return ()
    from ..evidence import schema, sync as sync_module

    try:
        rules = sync_module.load_manifest_rules(profile.manifest_path)
    except Exception:
        # An unparsable manifest is already reported by _manifest_freshness;
        # there is no usable source selection to compare the database against.
        return ()
    discovered = sync_module.discover_source_files(profile.input_root, rules)
    conn = schema.connect_existing(profile.database_path, read_only=True)
    try:
        schema.ensure_schema(conn)
        rows = {row["path"]: row["sha256"] for row in conn.execute("SELECT path, sha256 FROM sources")}
    finally:
        conn.close()
    diagnostics: list[str] = []
    for path in sorted(set(discovered) - set(rows)):
        diagnostics.append(f"documentation index database missing source: {path}")
    for path in sorted(set(rows) - set(discovered)):
        diagnostics.append(f"documentation index database has stale source: {path}")
    for path in sorted(set(discovered) & set(rows)):
        if sync_module.hash_file(discovered[path]) != rows[path]:
            diagnostics.append(f"documentation index database is stale relative to mirror: {path}")
    return tuple(diagnostics)


def docs_index_freshness_diagnostics(
    contract: DocsEvidenceContract,
    *,
    repo_root: str | Path,
) -> tuple[str, ...]:
    root = Path(repo_root).resolve()
    profile = resolve_docs_index_profile(contract)
    diagnostics = list(_index_input_freshness(contract, profile))
    diagnostics.extend(_manifest_freshness(contract, profile, root))
    if not profile.database_path.is_file():
        diagnostics.append("documentation index database is missing")
    else:
        diagnostics.extend(_database_freshness(profile))
    return tuple(diagnostics)


def doctor_docs_index(contract: DocsEvidenceContract, *, repo_root: str | Path) -> tuple[str, ...]:
    profile = resolve_docs_index_profile(contract)
    issues = list(docs_index_freshness_diagnostics(contract, repo_root=repo_root))
    if not profile.database_path.is_file():
        return tuple(issues)
    from ..evidence import schema, sync as sync_module

    conn = schema.connect_existing(profile.database_path, read_only=True)
    try:
        schema.ensure_schema(conn)
        issues.extend(sync_module.integrity_check(conn))
    finally:
        conn.close()
    return tuple(issues)
