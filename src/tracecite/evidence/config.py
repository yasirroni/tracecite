from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

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
    try:
        rules = load_manifest(profile_path)
    except ManifestError as exc:
        raise ConfigError(str(exc)) from exc
    for key in ("root", "database", "model_cache_dir"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ConfigError(f"TraceCite profile requires non-empty string {key}")
    base = profile_path.parent
    return TraceCiteProfile(
        root=_resolve(base, data["root"]),
        database=_resolve(base, data["database"]),
        model_cache_dir=_resolve(base, data["model_cache_dir"]),
        manifests=(profile_path,),
        rules=rules,
    )
