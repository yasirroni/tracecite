from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from .manifest import ManifestError, ManifestRules, load_manifest


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class TraceCiteProfile:
    root: Path
    database: Path
    model_cache_dir: Path
    manifests: tuple[Path, ...]
    rules: ManifestRules


def discover_profile(start: Path, explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return Path(explicit).resolve()
    return None


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def load_profile(path: Path) -> TraceCiteProfile:
    profile_path = Path(path).resolve()
    try:
        with profile_path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(str(exc)) from exc
    if data.get("schema_version") != 1:
        raise ConfigError("TraceCite profile requires schema_version = 1")
    unknown = set(data) - {"schema_version", "root", "database", "model_cache_dir", "source", "include", "exclude"}
    if unknown:
        raise ConfigError(f"unknown field(s) in TraceCite profile: {', '.join(sorted(unknown))}")
    base = profile_path.parent
    for key in ("root", "database", "model_cache_dir"):
        if key not in data or not isinstance(data[key], str) or not data[key].strip():
            raise ConfigError(f"TraceCite profile requires non-empty string {key}")
    root = _resolve(base, data.get("root", "."))
    try:
        rules = load_manifest(profile_path)
    except ManifestError as exc:
        raise ConfigError(str(exc)) from exc
    return TraceCiteProfile(
        root=root,
        database=_resolve(base, data["database"]),
        model_cache_dir=_resolve(base, data["model_cache_dir"]),
        manifests=(profile_path,),
        rules=rules,
    )
