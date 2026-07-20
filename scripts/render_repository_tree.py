"""Render a bounded repository tree for the documentation site."""

from __future__ import annotations

from pathlib import Path


_EXCLUDED_NAMES = {
    ".DS_Store",
    ".cache",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".quarto",
    ".ruff_cache",
    ".tracecite",
    ".venv",
    ".vscode",
    "__pycache__",
}
_EXCLUDED_SUFFIXES = (".egg-info",)
_EXCLUDED_FILENAMES = {"Manifest.toml"}
_EXCLUDED_PATHS = {
    ("docs", "build"),
    ("docs", "site_libs"),
}


def render_repository_tree(root: Path, *, max_depth: int = 3) -> str:
    """Return a text tree rooted at ``root`` up to ``max_depth`` levels."""

    root = root.resolve()
    if max_depth < 1:
        raise ValueError("max_depth must be at least 1")
    lines = ["."]
    _append_children(root, root, lines, prefix="", depth=1, max_depth=max_depth)
    return "\n".join(lines)


def _append_children(
    root: Path,
    directory: Path,
    lines: list[str],
    *,
    prefix: str,
    depth: int,
    max_depth: int,
) -> None:
    children = sorted(
        (
            path
            for path in directory.iterdir()
            if _is_visible(root, path)
            and (not path.is_dir() or _has_visible_entries(root, path))
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
            )


def _is_excluded(root: Path, path: Path) -> bool:
    relative = path.relative_to(root)
    if path.name in _EXCLUDED_NAMES or path.name in _EXCLUDED_FILENAMES:
        return True
    if path.name.endswith(_EXCLUDED_SUFFIXES):
        return True
    if path.suffix in {".html", ".quarto_ipynb"}:
        return True
    if relative.parts in _EXCLUDED_PATHS:
        return True
    return relative.parts[:1] in {("build",), ("dist",)}


def _is_visible(root: Path, path: Path) -> bool:
    """Whether ``path`` is a visible tree entry."""
    return not _is_excluded(root, path)


def _has_visible_entries(root: Path, directory: Path) -> bool:
    """Whether a directory has any visible file or non-empty directory."""
    if directory.is_symlink():
        return False
    for child in directory.iterdir():
        if not _is_visible(root, child):
            continue
        if child.is_symlink():
            if not child.is_dir():
                return True
            continue
        if (
            not child.is_dir()
            or _has_visible_entries(root, child)
        ):
            return True
    return False
