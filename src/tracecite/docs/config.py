"""TOML loading and deterministic validation for the docs contract."""

from __future__ import annotations

from pathlib import Path
import tomllib

from .contract import DocsEvidenceContract


_FIELDS = {
    "authored_root",
    "retained_root",
    "staged_root",
    "source_links",
    "index_output",
    "publication_exclude",
    "host_render_command",
}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _path(value: object, *, name: str, repo_root: Path, require_relative: bool = True) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty repository-relative path")
    raw = Path(value)
    if require_relative and raw.is_absolute():
        raise ValueError(f"{name} must be repository-relative")
    if require_relative and ".." in raw.parts:
        raise ValueError(f"{name} must not escape the repository")
    resolved = (repo_root / raw).resolve(strict=False)
    if not _inside(resolved, repo_root):
        raise ValueError(f"{name} resolves outside the repository")
    return resolved


def _overlap(left: Path, right: Path) -> bool:
    return _inside(left, right) or _inside(right, left)


def load_docs_contract(path: str | Path, *, repo_root: str | Path) -> DocsEvidenceContract:
    config_path = Path(path).resolve()
    root = Path(repo_root).resolve()
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"invalid docs configuration: {exc}") from exc
    if data.get("schema_version") != 1:
        raise ValueError("docs configuration requires schema_version = 1")
    if set(data) - {"schema_version", "docs"} or not isinstance(data.get("docs"), dict):
        raise ValueError("docs configuration requires a [docs] table")
    docs = data["docs"]
    unknown = set(docs) - _FIELDS
    if unknown:
        raise ValueError(f"unknown docs configuration field(s): {', '.join(sorted(unknown))}")
    missing = _FIELDS - set(docs) - {"host_render_command"}
    if missing:
        raise ValueError(f"missing docs configuration field(s): {', '.join(sorted(missing))}")

    authored = _path(docs.get("authored_root"), name="authored_root", repo_root=root)
    retained = _path(docs.get("retained_root"), name="retained_root", repo_root=root)
    staged = _path(docs.get("staged_root"), name="staged_root", repo_root=root)
    source_links = _path(docs.get("source_links"), name="source_links", repo_root=root)
    index_output = _path(docs.get("index_output"), name="index_output", repo_root=root)
    if not authored.is_dir() or not retained.is_dir():
        raise ValueError("authored_root and retained_root must be existing directories")
    if not source_links.is_file():
        raise ValueError("source_links must be an existing file")
    if _overlap(retained, staged):
        raise ValueError("retained_root and staged_root must not overlap")
    roots = (authored, retained, staged, source_links, index_output)
    for index, left in enumerate(roots):
        for right in roots[index + 1:]:
            if (left == authored and right == retained) or (left == retained and right == authored):
                if not _overlap(left, right) or left == right:
                    continue
                raise ValueError("authored_root and retained_root may overlap only when equal")
            if _overlap(left, right):
                raise ValueError("docs contract paths must not contain one another")

    excludes = docs.get("publication_exclude")
    if not isinstance(excludes, list):
        raise ValueError("publication_exclude must be an array")
    publication_exclude = tuple(
        _path(value, name="publication_exclude", repo_root=root) for value in excludes
    )
    command = docs.get("host_render_command")
    if command is not None:
        if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
            raise ValueError("host_render_command must be a non-empty argument array")
        command_tuple = tuple(command)
    else:
        command_tuple = None
    return DocsEvidenceContract(authored, retained, staged, source_links, index_output, publication_exclude, command_tuple)
