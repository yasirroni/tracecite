from __future__ import annotations

from pathlib import Path
import posixpath


class PathAuthorityError(ValueError):
    pass


def _lexical_posix(value: str | Path) -> str:
    return str(value).replace("\\", "/")


def normalise_relative_source_declaration(value: str | Path) -> str:
    text = _lexical_posix(value)
    if text.startswith("/") or text.startswith("//") or (len(text) >= 3 and text[1:3] == ":/"):
        raise PathAuthorityError(f"absolute source path is not allowed: {value}")
    parts: list[str] = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise PathAuthorityError(f"source path may not escape root: {value}")
        parts.append(part)
    if not parts:
        raise PathAuthorityError("source path is empty")
    return "/".join(parts)


def normalise_relative_glob_declaration(value: str | Path) -> str:
    text = _lexical_posix(value)
    if text.startswith("/") or text.startswith("//") or (len(text) >= 3 and text[1:3] == ":/"):
        raise PathAuthorityError(f"absolute source path is not allowed: {value}")
    parts: list[str] = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise PathAuthorityError(f"source path may not escape root: {value}")
        parts.append(part)
    if not parts:
        raise PathAuthorityError("source glob is empty")
    return "/".join(parts)


def normalise_source_path(root: Path, value: str | Path, *, base: Path | None = None) -> str:
    root = Path(root).resolve()
    text = _lexical_posix(value)
    if text == "":
        raise PathAuthorityError("source path is empty")

    raw_path = Path(text)
    if raw_path.is_absolute():
        candidate = raw_path
        display = text
    else:
        parts = [part for part in text.split("/") if part not in ("", ".")]
        depth = 0
        for part in parts:
            if part == "..":
                depth -= 1
            else:
                depth += 1
            if depth < 0 and base is None:
                raise PathAuthorityError(f"source path may not escape root: {value}")
        candidate = (Path(base).resolve() if base is not None else root) / Path(*parts)
        display = posixpath.normpath(text)

    resolved_parent = candidate.parent.resolve()
    resolved = (resolved_parent / candidate.name).resolve() if candidate.exists() else resolved_parent / candidate.name
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        message = "symlink resolves outside root" if candidate.is_symlink() else "source path is outside root"
        raise PathAuthorityError(f"{message}: {value}") from exc
    if candidate.is_symlink() and candidate.resolve() != resolved:
        raise PathAuthorityError(f"symlink resolves outside root: {value}")
    normalised = relative.as_posix()
    if normalised == "." or normalised.startswith("../"):
        raise PathAuthorityError(f"source path may not escape root: {value}")
    return normalised


def source_row_for_path(conn, path: str):
    normalised = _lexical_posix(path)
    row = conn.execute("SELECT * FROM sources WHERE path = ?", (normalised,)).fetchone()
    if row is not None:
        return row
    collapsed = posixpath.normpath(normalised)
    if collapsed != normalised:
        return conn.execute("SELECT * FROM sources WHERE path = ?", (collapsed,)).fetchone()
    return None
