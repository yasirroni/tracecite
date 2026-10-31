"""Small text helpers shared by Markdown and HTML table adapters."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

_ID_RE = re.compile(r"[^a-z0-9]+")
_TRAILING_ID_RE = re.compile(r"\s*\{#([A-Za-z][A-Za-z0-9_.:-]*)\}\s*$")
_NUMBER_WITH_UNIT_RE = re.compile(
    r"^\s*[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?\s*"
    r"([A-Za-zµμΩ°%$€£¥][A-Za-z0-9µμΩ°/%$€£¥·^*._-]*)\s*$"
)
_HEADER_UNIT_RE = re.compile(r"(?:\(([^()]*)\)|\[([^\[\]]*)\])\s*$")
_PIPE_SEPARATOR_RE = re.compile(r":?-{3,}:?")
_COMMON_LOWER_UNITS = {
    "bar",
    "degc",
    "degf",
    "g",
    "h",
    "hz",
    "kg",
    "km",
    "m",
    "min",
    "mm",
    "ms",
    "pa",
    "pu",
    "p.u.",
    "s",
}


def slug(value: str, fallback: str = "table") -> str:
    return _ID_RE.sub("-", value.lower()).strip("-") or fallback


def strip_caption_id(caption: str) -> tuple[str, str | None]:
    match = _TRAILING_ID_RE.search(caption)
    if not match:
        return caption.strip(), None
    return caption[: match.start()].strip(), match.group(1)


def collapse_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def split_pipe_row(line: str, clean=str.strip) -> list[str]:
    """Split one Markdown pipe-table row, honouring backslash escapes."""
    stripped = line.strip().removeprefix("|")
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in stripped:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "|":
            cells.append(clean("".join(current)))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    cells.append(clean("".join(current)))
    return cells


def is_pipe_table_start(lines: list[str], index: int) -> bool:
    """Whether ``lines[index]`` is a pipe-table header followed by its separator row."""
    if (
        index + 1 >= len(lines)
        or "|" not in lines[index]
        or "|" not in lines[index + 1]
    ):
        return False
    separator = split_pipe_row(lines[index + 1])
    return len(split_pipe_row(lines[index])) == len(separator) and all(
        _PIPE_SEPARATOR_RE.fullmatch(value) for value in separator
    )


def strip_html(value: str) -> str:
    return collapse_space(BeautifulSoup(value, "html.parser").get_text(" ", strip=True))


def escape_pipe_cell(value: str) -> str:
    text = str(value).replace("\\", "\\\\").replace("|", "\\|")
    return text.replace("\n", "<br>")


def escape_markdown_inline(value: str) -> str:
    text = str(value)
    for character in ("\\", "|", "$", "*", "_", "~", "`", "[", "]", "<", ">"):
        text = text.replace(character, f"\\{character}")
    return text


def normalise_label(value: str) -> str:
    if header_unit(value):
        value = _HEADER_UNIT_RE.sub("", value)
    return _ID_RE.sub(" ", value.lower()).strip()


def header_unit(value: str) -> str | None:
    match = _HEADER_UNIT_RE.search(value)
    if not match:
        return None
    unit = collapse_space(match.group(1) or match.group(2) or "")
    return unit if _looks_like_unit(unit) else None


def cell_unit(value: str) -> str | None:
    match = _NUMBER_WITH_UNIT_RE.match(value)
    return collapse_space(match.group(1)) if match else None


def is_missing(value: str) -> bool:
    return value.strip().lower() in {"", "na", "n/a", "nan", "null", "not available"}


def _looks_like_unit(value: str) -> bool:
    compact = collapse_space(value)
    if not compact or len(compact) > 32:
        return False
    if any(
        marker in compact for marker in ("°", "%", "/", "$", "€", "£", "¥", "·", "^")
    ):
        return True
    if " " in compact:
        return False
    if compact.casefold() in _COMMON_LOWER_UNITS:
        return True
    return any(character.isupper() or character.isdigit() for character in compact)
