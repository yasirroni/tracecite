from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Collection, Sequence
import fnmatch
import tomllib
from types import MappingProxyType

from .paths import PathAuthorityError, normalise_relative_glob_declaration, normalise_relative_source_declaration


SUPPORTED_EXTENSIONS = {".pdf", ".md"}
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
        normalised = normalise_relative_glob_declaration(value) if any(ch in str(value) for ch in "*?[") else normalise_relative_source_declaration(value)
    except PathAuthorityError as exc:
        raise ManifestError(str(exc)) from exc
    if Path(normalised).suffix.lower() not in SUPPORTED_EXTENSIONS and not any(ch in normalised for ch in "*?["):
        raise ManifestError(f"unsupported source extension for {value}")
    return normalised


def _matches(path: str, pattern: str) -> bool:
    if fnmatch.fnmatchcase(path, pattern):
        return True
    if "**/" in pattern and fnmatch.fnmatchcase(path, pattern.replace("**/", "")):
        return True
    return False


@dataclass(frozen=True)
class ManifestRules:
    explicit_paths: tuple[str, ...] = ()
    include_globs: tuple[str, ...] = ()
    exclude_globs: tuple[str, ...] = ()
    origins: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not isinstance(self.origins, MappingProxyType):
            object.__setattr__(self, "origins", MappingProxyType(dict(self.origins)))

    def selects_path(self, path: str) -> bool:
        path = str(path).replace("\\", "/")
        selected = path in self.explicit_paths or any(_matches(path, glob) for glob in self.include_globs)
        excluded = any(_matches(path, glob) for glob in self.exclude_globs)
        return selected and not excluded


@dataclass(frozen=True)
class SourceSelection:
    available_paths: tuple[str, ...]
    selected_existing_paths: tuple[str, ...]
    missing_explicit_paths: tuple[str, ...]
    unmatched_globs: tuple[str, ...]
    excluded_paths: tuple[str, ...]


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
    return ManifestRules(_unique(explicit), _unique(includes), _unique(excludes), MappingProxyType(dict(origins)))


def merge_manifests(paths: Sequence[Path]) -> ManifestRules:
    explicit: list[str] = []
    includes: list[str] = []
    excludes: list[str] = []
    seen_explicit: set[str] = set()
    seen_include: set[str] = set()
    seen_exclude: set[str] = set()
    origins: dict[tuple[str, str], str] = {}

    def add(kind: str, value: str, target: list[str], seen: set[str], origin: str) -> None:
        key = (kind, value)
        if value not in seen:
            target.append(value); seen.add(value)
        if origins.get(key) != "local" or origin == "local":
            origins[key] = origin

    for path in paths:
        rules = load_manifest(path)
        for item in rules.explicit_paths:
            add("source", item, explicit, seen_explicit, rules.origins.get(("source", item), "default"))
        for item in rules.include_globs:
            add("include", item, includes, seen_include, rules.origins.get(("include", item), "default"))
        for item in rules.exclude_globs:
            add("exclude", item, excludes, seen_exclude, rules.origins.get(("exclude", item), "default"))
    return ManifestRules(tuple(explicit), tuple(includes), tuple(excludes), MappingProxyType(dict(origins)))


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return tuple(out)


def _discover_declared(root: Path, rules: ManifestRules) -> tuple[str, ...]:
    root = Path(root).resolve()
    candidates: set[Path] = set()
    candidates.update(root / path for path in rules.explicit_paths)
    for pattern in rules.include_globs:
        candidates.update(root.glob(pattern))
    paths: list[str] = []
    for path in sorted(candidates):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError:
            continue
        paths.append(relative)
    return tuple(sorted(set(paths)))


def resolve_sources(root: Path, rules: ManifestRules, *, indexed_paths: Collection[str] = ()) -> SourceSelection:
    root = Path(root)
    discovered = _discover_declared(root, rules)
    excluded = tuple(sorted(path for path in discovered if any(_matches(path, glob) for glob in rules.exclude_globs)))
    available = tuple(sorted(path for path in discovered if rules.selects_path(path)))
    missing = tuple(path for path in rules.explicit_paths if path not in discovered)
    unmatched = tuple(glob for glob in rules.include_globs if not any(_matches(path, glob) for path in discovered))
    selected_existing = tuple(sorted(path for path in indexed_paths if rules.selects_path(path)))
    return SourceSelection(available, selected_existing, missing, unmatched, excluded)
