"""Deterministic symlink-based mirror synchronization for documentation variants."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence
import os


def _should_exclude(path: Path, variant: str | None = None) -> bool:
    """Check if a path should be excluded from mirroring."""
    name = path.name
    parts = path.parts

    # Always exclude build outputs, caches, and git
    excluded_dirs = {".git", ".quarto", "build", ".pytest_cache", ".venv", "dist"}
    if any(part in excluded_dirs for part in parts):
        return True

    # Exclude generated HTML and markdown
    if name.endswith(".html") or name.endswith("_files"):
        return True

    # Don't symlink dotfiles (git refuses to read symlinked .gitignore/.gitattributes)
    if name.startswith(".") and name not in {".gitignore", ".gitattributes"}:
        return True

    # Variant-specific exclusions
    if variant == "python":
        # Exclude Julia files for Python variant
        if name.endswith(".jl"):
            return True
    elif variant == "julia":
        # Exclude Python files for Julia variant
        if name.endswith(".py"):
            return True

    return False


def _get_mirror_structure(
    canonical_root: Path,
    variant: str | None = None,
) -> dict[str, Path | str]:
    """
    Compute the structure of symlinks to create in a mirror directory.

    Returns a mapping of relative mirror paths to either:
    - A Path to the canonical source (for symlinks)
    - A string (YAML content for _quarto.yml files)

    Does not traverse into build, caches, or generated output.
    """
    structure: dict[str, Path | str] = {}
    canonical_root = Path(canonical_root).resolve()

    # Walk canonical tree
    for item in sorted(canonical_root.rglob("*")):
        if item == canonical_root:
            continue

        # Skip excluded paths
        if _should_exclude(item, variant):
            continue

        rel_path = item.relative_to(canonical_root)

        if item.is_dir():
            # Directories are represented implicitly (created as needed for symlinks)
            pass
        elif item.is_file():
            # Skip _quarto*.yml at root (these will be real files in mirrors)
            if item.parent == canonical_root and item.name.startswith("_quarto"):
                continue
            # All other files get symlinked
            structure[str(rel_path)] = item.resolve()

    return structure


def sync_mirror_symlinks(
    canonical_root: Path,
    mirror_root: Path,
    variant: str | None = None,
    quarto_config: str | None = None,
) -> dict[str, str]:
    """
    Create or update a deterministic symlink mirror of canonical content.

    This function:
    - Creates only managed symlinks using relative paths (never copies files)
    - Creates intermediate directories as needed
    - Removes stale symlinks that are no longer in the expected structure
    - Refuses to overwrite or delete real (non-symlink) files except quarto configs
    - Writes real .gitignore files (git refuses symlinked .gitignore for security)
    - Returns a manifest of created/updated symlinks

    Args:
        canonical_root: Source of canonical documentation
        mirror_root: Target mirror directory (created if needed)
        variant: "python" or "julia" to filter content
        quarto_config: Real YAML content for _quarto.yml (if provided)

    Returns:
        Manifest dict with keys: "created", "updated", "removed", "skipped_real"
    """
    canonical_root = Path(canonical_root).resolve()
    mirror_root = Path(mirror_root).resolve()

    if not canonical_root.is_dir():
        raise ValueError(f"Canonical root does not exist: {canonical_root}")

    mirror_root.mkdir(parents=True, exist_ok=True)

    expected = _get_mirror_structure(canonical_root, variant)

    manifest = {
        "created": [],
        "updated": [],
        "removed": [],
        "skipped_real": [],
    }

    # Create/update symlinks and directories
    for rel_path_str, target in expected.items():
        mirror_path = mirror_root / rel_path_str

        # Ensure parent directories exist
        mirror_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(target, str):
            # This shouldn't happen in current flow (reserved for future YAML handling)
            continue

        # Special handling for .gitignore: write real file, don't symlink
        # (git refuses to read symlinked .gitignore files)
        if mirror_path.name == ".gitignore":
            canonical_gitignore = canonical_root / ".gitignore"
            if canonical_gitignore.is_file():
                content = canonical_gitignore.read_text(encoding="utf-8")
                mirror_path.write_text(content, encoding="utf-8")
                manifest["created"].append(rel_path_str)
            continue

        # Handle existing path at mirror location
        if mirror_path.exists() or mirror_path.is_symlink():
            # If it's already the correct symlink, skip it
            if mirror_path.is_symlink():
                try:
                    if mirror_path.resolve() == target:
                        continue
                except (OSError, RuntimeError):
                    # Broken symlink, will be replaced below
                    pass

            # If it's a real file (not a symlink), refuse to overwrite
            if mirror_path.is_file() and not mirror_path.is_symlink():
                manifest["skipped_real"].append(rel_path_str)
                continue

            # If it's a symlink to something else, update it
            if mirror_path.is_symlink():
                mirror_path.unlink()
                # Compute relative path from mirror location to target
                rel_target = os.path.relpath(target, start=mirror_path.parent)
                os.symlink(rel_target, mirror_path)
                manifest["updated"].append(rel_path_str)
                continue

            # If it's a directory, refuse to replace
            if mirror_path.is_dir():
                manifest["skipped_real"].append(rel_path_str)
                continue

        # Create new symlink with relative path
        rel_target = os.path.relpath(target, start=mirror_path.parent)
        os.symlink(rel_target, mirror_path)
        manifest["created"].append(rel_path_str)

    # Remove stale symlinks (those in mirror but not in expected structure)
    for item in list(mirror_root.rglob("*")):
        if item == mirror_root:
            continue

        rel_path = item.relative_to(mirror_root)

        # Skip real files (non-symlinks) except in special cases
        if item.is_file() and not item.is_symlink():
            # Allow real _quarto*.yml files and .gitignore files
            if item.parent == mirror_root and (item.name.startswith("_quarto") or item.name == ".gitignore"):
                continue
            # Skip other real files
            continue

        # If it's a symlink not in expected, remove it
        if item.is_symlink() and str(rel_path) not in expected:
            item.unlink()
            manifest["removed"].append(str(rel_path))

        # If it's an empty directory not in expected, optionally clean it
        # (We don't do this to preserve structure)

    return manifest


def verify_symlink_mirror(
    mirror_root: Path,
    canonical_root: Path,
    variant: str | None = None,
) -> dict[str, int | list[str]]:
    """
    Verify that a mirror contains only managed symlinks pointing to canonical.

    Returns a status dict with:
    - symlink_count: Number of symlinks
    - real_file_count: Number of real files (should be just _quarto.yml variants)
    - directory_count: Number of directories
    - errors: List of issues found
    """
    mirror_root = Path(mirror_root).resolve()
    canonical_root = Path(canonical_root).resolve()

    status = {
        "symlink_count": 0,
        "real_file_count": 0,
        "directory_count": 0,
        "errors": [],
    }

    for item in mirror_root.rglob("*"):
        if item == mirror_root:
            continue

        if item.is_symlink():
            status["symlink_count"] += 1
            # Verify symlink points to canonical
            try:
                resolved = item.resolve()
                if not str(resolved).startswith(str(canonical_root)):
                    status["errors"].append(
                        f"Symlink points outside canonical: {item} -> {resolved}"
                    )
            except Exception as e:
                status["errors"].append(
                    f"Broken symlink: {item}: {e}"
                )
        elif item.is_file():
            status["real_file_count"] += 1
            # Only _quarto*.yml should be real files
            if not (item.parent == mirror_root and item.name.startswith("_quarto")):
                status["errors"].append(
                    f"Unexpected real file: {item}"
                )
        elif item.is_dir():
            status["directory_count"] += 1

    return status


def snapshot_canonical_bytes(root: Path) -> dict[Path, bytes]:
    """
    Snapshot all canonical content bytes before a mirror build.

    Used to detect mutations through symlinks.
    """
    root = Path(root).resolve()
    snapshot: dict[Path, bytes] = {}

    for item in root.rglob("*"):
        if item.is_file() and not item.is_symlink():
            # Skip build artifacts, caches
            parts = item.relative_to(root).parts
            if any(part in {".quarto", "build", ".pytest_cache"} for part in parts):
                continue
            snapshot[item.relative_to(root)] = item.read_bytes()

    return snapshot


def verify_no_mutation(
    before: dict[Path, bytes],
    canonical_root: Path,
) -> tuple[list[Path], list[Path]]:
    """
    Verify that canonical content has not been mutated.

    Returns (unchanged_paths, changed_paths).
    """
    canonical_root = Path(canonical_root).resolve()

    after: dict[Path, bytes] = {}
    for item in canonical_root.rglob("*"):
        if item.is_file() and not item.is_symlink():
            parts = item.relative_to(canonical_root).parts
            if any(part in {".quarto", "build", ".pytest_cache"} for part in parts):
                continue
            after[item.relative_to(canonical_root)] = item.read_bytes()

    unchanged = []
    changed = []

    all_paths = set(before.keys()) | set(after.keys())
    for rel_path in sorted(all_paths):
        if before.get(rel_path) == after.get(rel_path):
            unchanged.append(rel_path)
        else:
            changed.append(rel_path)

    return unchanged, changed
