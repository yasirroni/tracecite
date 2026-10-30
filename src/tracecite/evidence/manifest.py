from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Mapping, Sequence
import fnmatch
import tomllib
from types import MappingProxyType

from .paths import PathAuthorityError, normalise_relative_declaration


SOURCE_TYPES = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".xlsx": "workbook",
    ".xlsm": "workbook",
}
_TOP_LEVEL_KEYS = {"schema_version", "root", "database", "model_cache_dir", "source", "include", "exclude"}
_TABLE_KEYS = {
    "source": {"path", "origin"},
    "include": {"glob", "origin"},
    "exclude": {"glob", "origin"},
}
_REQUIRED_TABLE_KEYS = {
    "source": {"path"},
    "include": {"glob"},
    "exclude": {"glob"},
}
_ORIGINS = {"default", "local"}


class ManifestError(ValueError):
    pass


def _normalise(value: str | Path) -> str:
    try:
        normalised = normalise_relative_declaration(value)
    except PathAuthorityError as exc:
        raise ManifestError(str(exc)) from exc
    if Path(normalised).suffix.lower() not in SOURCE_TYPES and not any(ch in normalised for ch in "*?["):
        raise ManifestError(f"unsupported source extension for {value}")
    return normalised


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern) or ("**/" in pattern and fnmatch.fnmatchcase(path, pattern.replace("**/", "")))


@dataclass(frozen=True)
class ManifestRules:
    explicit_paths: tuple[str, ...] = ()
    include_globs: tuple[str, ...] = ()
    exclude_globs: tuple[str, ...] = ()
    origins: Mapping[tuple[str, str], str] = field(default_factory=lambda: MappingProxyType({}))

    def selects_path(self, path: str) -> bool:
        path = str(path).replace("\\", "/")
        selected = path in self.explicit_paths or any(_matches(path, glob) for glob in self.include_globs)
        excluded = any(_matches(path, glob) for glob in self.exclude_globs)
        return selected and not excluded


@dataclass(frozen=True)
class SourceSelection:
    selected: dict[str, Path]
    missing_explicit_paths: tuple[str, ...]
    unmatched_globs: tuple[str, ...]


def load_manifest(path: Path) -> ManifestRules:
    with Path(path).open("rb") as handle:
        data = tomllib.load(handle)
    if data.get("schema_version") != 1:
        raise ManifestError(f"{path} requires schema_version = 1")
    unknown = set(data) - _TOP_LEVEL_KEYS
    if unknown:
        raise ManifestError(f"unknown field(s) in {path}: {', '.join(sorted(unknown))}")

    origins: dict[tuple[str, str], str] = {}

    def table_values(name: str, field: str) -> tuple[str, ...]:
        values = []
        for index, item in enumerate(data.get(name, []), start=1):
            if not isinstance(item, dict):
                raise ManifestError(f"[[{name}]] entry {index} must be a table")
            keys = set(item)
            unknown_keys = keys - _TABLE_KEYS[name]
            missing = _REQUIRED_TABLE_KEYS[name] - keys
            if unknown_keys:
                raise ManifestError(f"unknown field(s) in [[{name}]] entry {index}: {', '.join(sorted(unknown_keys))}")
            if missing:
                raise ManifestError(f"missing field(s) in [[{name}]] entry {index}: {', '.join(sorted(missing))}")
            origin = item.get("origin", "default")
            if origin not in _ORIGINS:
                raise ManifestError(f"unsupported origin in [[{name}]] entry {index}: {origin}")
            identity = _normalise(item[field])
            values.append(identity)
            key = (name, identity)
            if origins.get(key) != "local" or origin == "local":
                origins[key] = origin
        return tuple(values)

    explicit = table_values("source", "path")
    includes = table_values("include", "glob")
    excludes = table_values("exclude", "glob")
    return ManifestRules(
        tuple(dict.fromkeys(explicit)),
        tuple(dict.fromkeys(includes)),
        tuple(dict.fromkeys(excludes)),
        MappingProxyType(origins),
    )


def merge_manifests(paths: Sequence[Path]) -> ManifestRules:
    """Union manifests in order; a ``local`` origin wins over ``default`` for the same declaration."""
    declared: dict[str, dict[str, None]] = {"source": {}, "include": {}, "exclude": {}}
    origins: dict[tuple[str, str], str] = {}
    for path in paths:
        rules = load_manifest(path)
        for kind, values in (("source", rules.explicit_paths), ("include", rules.include_globs), ("exclude", rules.exclude_globs)):
            for value in values:
                declared[kind][value] = None
                origin = rules.origins.get((kind, value), "default")
                if origins.get((kind, value)) != "local" or origin == "local":
                    origins[(kind, value)] = origin
    return ManifestRules(
        tuple(declared["source"]),
        tuple(declared["include"]),
        tuple(declared["exclude"]),
        MappingProxyType(origins),
    )


def resolve_sources(root: Path, rules: ManifestRules) -> SourceSelection:
    """Scan the declared paths and globs once under ``root``.

    ``selected`` maps each existing, non-symlink, supported file that the
    rules select to its resolved path. Missing explicit paths and include
    globs that match no file are judged before exclusions apply.
    """
    root = Path(root).resolve()
    candidates = {root / path for path in rules.explicit_paths}
    for pattern in rules.include_globs:
        candidates.update(root.glob(pattern))
    declared: dict[str, Path] = {}
    for path in sorted(candidates):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in SOURCE_TYPES:
            continue
        resolved = path.resolve()
        if resolved.is_relative_to(root):
            declared[resolved.relative_to(root).as_posix()] = resolved
    return SourceSelection(
        selected={path: resolved for path, resolved in declared.items() if rules.selects_path(path)},
        missing_explicit_paths=tuple(path for path in rules.explicit_paths if path not in declared),
        unmatched_globs=tuple(glob for glob in rules.include_globs if not any(_matches(path, glob) for path in declared)),
    )
