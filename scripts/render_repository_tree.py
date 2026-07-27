"""Render a bounded repository tree for the documentation site."""

from __future__ import annotations

import subprocess
from pathlib import Path


_EXCLUDED_NAMES = {
    "__pycache__",
}
_EXCLUDED_SUFFIXES = (".egg-info",)
_EXCLUDED_FILENAMES = {"Manifest.toml"}
_EXCLUDED_PATHS = {
    (".superpowers",),
    ("docs", "build"),
    ("docs", "site_libs"),
}


def render_repository_tree(root: Path, *, max_depth: int = 3) -> str:
    """Return a text tree rooted at ``root`` up to ``max_depth`` levels."""

    root = root.resolve()
    if max_depth < 1:
        raise ValueError("max_depth must be at least 1")
    git_visible_files = _git_visible_files(root)
    lines = ["."]
    _append_children(
        root,
        root,
        lines,
        prefix="",
        depth=1,
        max_depth=max_depth,
        git_visible_files=git_visible_files,
    )
    return "\n".join(lines)


def _git_visible_files(root: Path) -> frozenset[tuple[str, ...]] | None:
    """Return Git-visible files, or ``None`` outside a Git work tree.

    Tracked files and untracked files that are not ignored are included. Git is
    the authority for nested ``.gitignore`` files, negation rules, and any
    repository-local exclude configuration.
    """

    try:
        result = subprocess.run(
            (
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
            ),
            check=False,
            capture_output=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return frozenset(
        Path(raw.decode("utf-8", errors="surrogateescape")).parts
        for raw in result.stdout.split(b"\0")
        if raw
    )


def _append_children(
    root: Path,
    directory: Path,
    lines: list[str],
    *,
    prefix: str,
    depth: int,
    max_depth: int,
    git_visible_files: frozenset[tuple[str, ...]] | None,
) -> None:
    children = sorted(
        (
            path
            for path in directory.iterdir()
            if _is_visible(root, path, git_visible_files)
            and (
                not path.is_dir()
                or _has_visible_entries(root, path, git_visible_files)
            )
        ),
        key=lambda path: (not path.is_dir(), path.name.casefold()),
    )
    for index, child in enumerate(children):
        last = index == len(children) - 1
        connector = "└── " if last else "├── "
        label = child.name + ("/" if child.is_dir() else "")
        lines.append(f"{prefix}{connector}{label}")
        if child.is_dir() and not child.is_symlink() and depth < max_depth:
            continuation = "    " if last else "│   "
            _append_children(
                root,
                child,
                lines,
                prefix=prefix + continuation,
                depth=depth + 1,
                max_depth=max_depth,
                git_visible_files=git_visible_files,
            )


def _is_excluded(root: Path, path: Path) -> bool:
    relative = path.relative_to(root)
    if path.name.startswith("."):
        return True
    if path.name in _EXCLUDED_NAMES or path.name in _EXCLUDED_FILENAMES:
        return True
    if path.name.endswith(_EXCLUDED_SUFFIXES):
        return True
    if path.suffix in {".html", ".quarto_ipynb"}:
        return True
    if relative.parts in _EXCLUDED_PATHS:
        return True
    return relative.parts[:1] in {("build",), ("dist",)}


def _is_visible(
    root: Path,
    path: Path,
    git_visible_files: frozenset[tuple[str, ...]] | None = None,
) -> bool:
    """Whether ``path`` is a visible tree entry."""
    if _is_excluded(root, path):
        return False
    if git_visible_files is None:
        return True
    relative_parts = path.relative_to(root).parts
    if path.is_dir():
        return any(
            parts[: len(relative_parts)] == relative_parts
            for parts in git_visible_files
        )
    return relative_parts in git_visible_files


def _has_visible_entries(
    root: Path,
    directory: Path,
    git_visible_files: frozenset[tuple[str, ...]] | None = None,
) -> bool:
    """Whether a directory has any visible file or non-empty directory."""
    if directory.is_symlink():
        return False
    for child in directory.iterdir():
        if not _is_visible(root, child, git_visible_files):
            continue
        if child.is_symlink():
            if not child.is_dir():
                return True
            continue
        if (
            not child.is_dir()
            or _has_visible_entries(root, child, git_visible_files)
        ):
            return True
    return False
