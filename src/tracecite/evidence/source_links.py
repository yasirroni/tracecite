"""Lightweight schema-v3 source-link registry and destination parsing.

The registry maps one stable local ``.pdf`` or ``.md`` source path to a
public HTTPS destination for documentation-link routing and report-source
validation. It intentionally carries only ``name``, ``local_path``, and
``public_url`` plus an opaque optional ``metadata`` table; it is not a
bibliography, citation-key, or remote-ingestion system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re
import tomllib
from urllib.parse import urlparse

from .paths import PathAuthorityError, normalise_source_path

SCHEMA_VERSION = 3

_SOURCE_LINK_REQUIRED = {"name", "local_path", "public_url"}
_SOURCE_LINK_OPTIONAL = {"metadata"}
_ROUTABLE_EXTENSIONS = (".pdf", ".md")


@dataclass(frozen=True)
class SourceLinkEntry:
    name: str
    local_path: str
    public_url: str
    metadata: dict[str, Any] = field(default_factory=dict)


def load_source_links(path: Path, source_links_root: Path) -> tuple[dict[Path, list[SourceLinkEntry]], list[str]]:
    with Path(path).open("rb") as handle:
        data = tomllib.load(handle)
    issues: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        return {}, [f"{path} requires schema_version = {SCHEMA_VERSION}"]
    source_entries = data.get("source", [])
    if not isinstance(source_entries, list):
        return {}, [f"{path} field source must be an array of tables"]
    registry: dict[Path, list[SourceLinkEntry]] = {}
    seen_paths: set[Path] = set()
    seen_names: set[str] = set()
    for index, entry in enumerate(source_entries, start=1):
        if not isinstance(entry, dict):
            issues.append(f"source entry {index} must be a table")
            continue
        keys = set(entry)
        unknown = keys - _SOURCE_LINK_REQUIRED - _SOURCE_LINK_OPTIONAL
        missing = _SOURCE_LINK_REQUIRED - keys
        if unknown:
            issues.append(f"source entry {index} has unknown field(s): {', '.join(sorted(unknown))}")
            continue
        if missing:
            issues.append(f"source entry {index} missing required field(s): {', '.join(sorted(missing))}")
            continue
        invalid_fields = [
            field_name
            for field_name in sorted(_SOURCE_LINK_REQUIRED)
            if not isinstance(entry[field_name], str) or not entry[field_name].strip()
        ]
        if invalid_fields:
            issues.extend(f"source entry {index} field {field_name} must be a non-empty string" for field_name in invalid_fields)
            continue
        metadata = entry.get("metadata", {})
        if not isinstance(metadata, dict):
            issues.append(f"source entry {index} field metadata must be a table")
            continue
        if any(character in entry["local_path"] for character in "?#"):
            issues.append(f"source entry {index} local_path must not contain a query or fragment")
            continue
        try:
            local_path = normalise_source_path(source_links_root, entry["local_path"])
        except PathAuthorityError as exc:
            issues.append(f"source entry {index} invalid local_path: {exc}")
            continue
        if not local_path.lower().endswith(_ROUTABLE_EXTENSIONS):
            issues.append(f"source entry {index} local_path must end in .pdf or .md")
            continue
        local_abs = (source_links_root / local_path).resolve()
        if local_abs in seen_paths:
            issues.append(f"duplicate source-link local_path: {local_path}")
            continue
        name = entry["name"]
        if name in seen_names:
            issues.append(f"duplicate source-link name: {name}")
            continue
        parsed_url = urlparse(entry["public_url"])
        if (
            parsed_url.scheme != "https" or not parsed_url.netloc
            or parsed_url.username is not None or parsed_url.password is not None
            or parsed_url.fragment
        ):
            issues.append(f"source entry {index} public_url must be an HTTPS URL without credentials or fragment")
            continue
        seen_paths.add(local_abs)
        seen_names.add(name)
        registry.setdefault(local_abs, []).append(SourceLinkEntry(name, local_path, entry["public_url"], metadata))
    return registry, issues


_REFERENCE_DESTINATION_RE = re.compile(
    r"^(?:<(?P<angle>.*?)#page=(?P<angle_page>-?\d+)>|(?P<bare>.*?)#page=(?P<bare_page>-?\d+))$"
)


def parse_source_link_destination(destination: str) -> tuple[str, int] | None:
    """Parse a positive-page PDF reference destination while retaining verifier diagnostics."""
    match = _REFERENCE_DESTINATION_RE.fullmatch(destination)
    if match is None:
        return None
    path = match.group("angle") or match.group("bare") or ""
    page = match.group("angle_page") or match.group("bare_page")
    return path.replace(r"\ ", " "), int(page)


def parse_staged_source_destination(destination: str) -> tuple[str, int] | None:
    """Parse a narrow local PDF `#page=N` destination for stage rewriting."""
    parsed = parse_source_link_destination(destination)
    if parsed is None:
        return None
    path, page = parsed
    if (
        page <= 0
        or any(character in path for character in "?#()<>\t\r\n")
        or any(character.isspace() for character in path)
        or not path.lower().endswith(".pdf")
    ):
        return None
    return path, page


def parse_staged_markdown_destination(destination: str) -> tuple[str, str] | None:
    """Parse a narrow local `.md` or `.md#anchor` destination for stage rewriting.

    Returns ``(path, anchor)`` with ``anchor`` the empty string when no
    fragment was authored, or ``None`` when the destination is not a
    supported local Markdown routing candidate (remote, query-bearing,
    angle-wrapped, malformed, or wrong-extension destinations all return
    ``None`` so the caller can leave them untouched rather than erroring).
    """
    if (
        not destination
        or "?" in destination
        or "://" in destination
        or destination.startswith("<")
        or destination.count("#") > 1
    ):
        return None
    path, separator, anchor = destination.partition("#")
    if separator and not anchor:
        return None
    if (
        not path
        or any(character in path for character in "?#()<>\t\r\n")
        or any(character.isspace() for character in path)
        or not path.lower().endswith(".md")
    ):
        return None
    if any(character.isspace() for character in anchor) or any(character in anchor for character in "()<>"):
        return None
    return path, anchor
