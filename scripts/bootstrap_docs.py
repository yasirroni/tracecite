#!/usr/bin/env python3
"""Bootstrap ordinary-file copies of canonical docs/ into derived doc projects.

Repository-only tool: this lives in ``scripts/`` and is never part of the
installed ``tracecite`` package. It replaces the former symlink mirrors
(which broke Quarto's own resource-copy step with a duplicate-target
collision) with plain managed files plus a tracked per-project manifest, so
neither ``git status`` nor Quarto ever has to reason about symlinks in a
derived project.

Usage:
    python scripts/bootstrap_docs.py            # bootstrap all managed files
    python scripts/bootstrap_docs.py --check    # read-only: report drift only
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP_CONFIG = ROOT / "docs" / "bootstrap.toml"
MANIFEST_NAME = ".docs-bootstrap-manifest.json"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Mapping:
    source: Path
    destination: Path


@dataclass(frozen=True)
class ProjectPolicy:
    owned: frozenset[str]
    ignored: tuple[str, ...]


DEFAULT_IGNORED = (
    "build/**",
    ".quarto/**",
    "site_libs/**",
    "**/__pycache__/**",
    "*.html",
    "**/*.html",
    "*.html.md",
    "**/*.html.md",
    "*.quarto_ipynb",
    "**/*.quarto_ipynb",
    ".DS_Store",
    "**/.DS_Store",
)


def _load_config(config_path: Path) -> tuple[list[Mapping], dict[str, ProjectPolicy]]:
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{config_path} requires schema_version = {SCHEMA_VERSION}")
    entries = data.get("mapping")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{config_path} requires a non-empty [[mapping]] array")
    mappings: list[Mapping] = []
    seen_destinations: set[Path] = set()
    for index, entry in enumerate(entries, start=1):
        source = entry.get("source")
        destinations = entry.get("destinations")
        if not isinstance(source, str) or not source:
            raise ValueError(f"mapping {index}: source must be a non-empty string")
        if not isinstance(destinations, list) or not destinations or not all(
            isinstance(item, str) and item for item in destinations
        ):
            raise ValueError(f"mapping {index}: destinations must be a non-empty array of strings")
        source_path = (ROOT / source).resolve()
        if not source_path.is_file():
            raise ValueError(f"mapping {index}: source does not exist: {source}")
        for destination in destinations:
            # Do not use .resolve() here: today's destinations are still the old
            # symlinks pointing at canonical docs/, so resolving would collapse
            # every destination onto the same canonical source path and make
            # legitimate distinct destinations look like duplicates.
            destination_path = ROOT / destination
            if destination_path in seen_destinations:
                raise ValueError(f"mapping {index}: destination mapped more than once: {destination}")
            seen_destinations.add(destination_path)
            mappings.append(Mapping(source_path, destination_path))

    policies: dict[str, ProjectPolicy] = {}
    for index, entry in enumerate(data.get("project", []), start=1):
        name = entry.get("name")
        owned = entry.get("owned", [])
        ignored = entry.get("ignored", [])
        if not isinstance(name, str) or not name:
            raise ValueError(f"project {index}: name must be a non-empty string")
        if name in policies:
            raise ValueError(f"project {index}: duplicate project policy: {name}")
        if not isinstance(owned, list) or not all(
            isinstance(item, str) and item for item in owned
        ):
            raise ValueError(f"project {index}: owned must be an array of strings")
        if not isinstance(ignored, list) or not all(
            isinstance(item, str) and item for item in ignored
        ):
            raise ValueError(f"project {index}: ignored must be an array of strings")
        policies[name] = ProjectPolicy(
            owned=frozenset(owned),
            ignored=tuple(DEFAULT_IGNORED) + tuple(ignored),
        )
    return mappings, policies


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _project_name_for(destination: Path) -> str:
    return Path(os.path.relpath(destination, ROOT)).parts[0]


def _load_previous_manifest(project_dir: Path) -> dict:
    manifest_path = project_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return {"schema_version": SCHEMA_VERSION, "project": project_dir.name, "files": {}}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _expected_by_project(mappings: list[Mapping]) -> dict[str, dict[str, dict[str, str]]]:
    """Return {project_name: {destination_relative_to_project: {source, sha256}}}."""
    expected: dict[str, dict[str, dict[str, str]]] = {}
    for mapping in mappings:
        project = _project_name_for(mapping.destination)
        project_dir = ROOT / project
        relative = mapping.destination.relative_to(project_dir).as_posix()
        source_relative = mapping.source.relative_to(ROOT).as_posix()
        expected.setdefault(project, {})[relative] = {
            "source": source_relative,
            "sha256": _sha256(mapping.source),
        }
    return expected


def _matches_ignored(relative: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            if relative == prefix or relative.startswith(prefix + "/"):
                return True
        if fnmatch.fnmatchcase(relative, pattern):
            return True
    return False


def check(
    mappings: list[Mapping],
    policies: dict[str, ProjectPolicy] | None = None,
) -> list[str]:
    issues: list[str] = []
    policies = policies or {}
    for project, files in _expected_by_project(mappings).items():
        project_dir = ROOT / project
        policy = policies.get(project, ProjectPolicy(frozenset(), DEFAULT_IGNORED))
        previous_files = _load_previous_manifest(project_dir).get("files", {})
        for relative, info in files.items():
            destination = project_dir / relative
            if destination.is_symlink():
                issues.append(f"{project}: {relative} is a symlink, expected an ordinary file")
                continue
            if not destination.is_file():
                issues.append(f"{project}: missing managed file {relative}")
                continue
            if relative not in previous_files:
                issues.append(f"{project}: unrecorded managed file {relative} (not in manifest)")
            if _sha256(destination) != info["sha256"]:
                issues.append(f"{project}: {relative} is stale relative to canonical {info['source']}")
        for relative in sorted(set(previous_files) - set(files)):
            destination = project_dir / relative
            if destination.exists() or destination.is_symlink():
                issues.append(f"{project}: obsolete managed file {relative} (no longer mapped)")

        allowed = set(files) | set(policy.owned) | {MANIFEST_NAME}
        for path in sorted(project_dir.rglob("*")):
            if not (path.is_file() or path.is_symlink()):
                continue
            relative = path.relative_to(project_dir).as_posix()
            if relative in allowed or _matches_ignored(relative, policy.ignored):
                continue
            issues.append(f"{project}: unexpected unowned file {relative}")
    return issues


def _promote_project(
    project_dir: Path,
    files: dict[str, dict[str, str]],
    previous_files: dict[str, dict[str, str]],
    staged_root: Path,
) -> None:
    """Replace one project's managed state atomically with rollback on failure."""
    manifest_path = project_dir / MANIFEST_NAME
    affected = sorted(set(files) | set(previous_files))
    backup_root = Path(tempfile.mkdtemp(prefix=".bootstrap-backup-", dir=project_dir.parent))
    moved: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for relative in [*affected, MANIFEST_NAME]:
            destination = project_dir / relative
            if not (destination.exists() or destination.is_symlink()):
                continue
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(destination, backup)
            moved.append((destination, backup))

        for relative in files:
            destination = project_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_root / relative, destination)
            installed.append(destination)
        os.replace(staged_root / MANIFEST_NAME, manifest_path)
        installed.append(manifest_path)
    except BaseException:
        for destination in reversed(installed):
            if destination.is_file() or destination.is_symlink():
                destination.unlink()
        for destination, backup in reversed(moved):
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, destination)
        raise
    finally:
        shutil.rmtree(backup_root, ignore_errors=True)


def bootstrap(mappings: list[Mapping]) -> None:
    for project, files in _expected_by_project(mappings).items():
        project_dir = ROOT / project
        previous_files = _load_previous_manifest(project_dir).get("files", {})

        # Conflict detection: a destination is safe to (re)write if it doesn't
        # exist, is a symlink (always a prior-mechanism artifact, never real
        # authored content), or was already recorded as a managed file by an
        # earlier bootstrap run. Anything else -- an unrecorded real file or a
        # directory sitting where a managed file belongs -- is a conflict.
        for relative in files:
            destination = project_dir / relative
            if destination.is_symlink():
                continue
            if destination.is_dir():
                raise SystemExit(
                    f"refusing to bootstrap {project}: {relative} is an unmanaged directory"
                )
            if destination.is_file() and relative not in previous_files:
                raise SystemExit(
                    f"refusing to bootstrap {project}: {relative} exists but is not a "
                    f"previously managed file (conflict) -- resolve manually first"
                )

        temp_dir = Path(tempfile.mkdtemp(prefix=".bootstrap-", dir=project_dir.parent))
        try:
            for relative, info in files.items():
                staged = temp_dir / relative
                staged.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / info["source"], staged)
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "project": project,
                "files": {relative: dict(info) for relative, info in files.items()},
            }
            staged_manifest = temp_dir / MANIFEST_NAME
            staged_manifest.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

            _promote_project(project_dir, files, previous_files, temp_dir)
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report drift without writing")
    args = parser.parse_args(argv)

    mappings, policies = _load_config(BOOTSTRAP_CONFIG)
    if args.check:
        issues = check(mappings, policies)
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1 if issues else 0

    bootstrap(mappings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
