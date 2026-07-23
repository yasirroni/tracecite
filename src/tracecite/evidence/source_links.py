"""Lightweight schema-v2 source-link registry and Markdown destination parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib
from urllib.parse import urlparse

from .paths import PathAuthorityError, normalise_source_path


@dataclass(frozen=True)
class SourceLinkEntry:
    local_path: str
    public_url: str


_SOURCE_LINK_REQUIRED = {"title", "publisher", "local_path", "public_url", "public_origin"}


def load_source_links(path: Path, source_links_root: Path) -> tuple[dict[Path, list[SourceLinkEntry]], list[str]]:
    with Path(path).open("rb") as handle:
        data = tomllib.load(handle)
    issues: list[str] = []
    if data.get("schema_version") != 2:
        return {}, [f"{path} requires schema_version = 2"]
    source_entries = data.get("source", [])
    if not isinstance(source_entries, list):
        return {}, [f"{path} field source must be an array of tables"]
    registry: dict[Path, list[SourceLinkEntry]] = {}
    seen: set[Path] = set()
    for index, entry in enumerate(source_entries, start=1):
        if not isinstance(entry, dict):
            issues.append(f"source entry {index} must be a table")
            continue
        keys = set(entry)
        unknown = keys - _SOURCE_LINK_REQUIRED
        missing = _SOURCE_LINK_REQUIRED - keys
        if unknown:
            issues.append(f"source entry {index} has unknown field(s): {', '.join(sorted(unknown))}")
            continue
        if missing:
            issues.append(f"source entry {index} missing required field(s): {', '.join(sorted(missing))}")
            continue
        invalid_fields = [field for field in sorted(_SOURCE_LINK_REQUIRED) if not isinstance(entry[field], str) or not entry[field].strip()]
        if invalid_fields:
            issues.extend(f"source entry {index} field {field} must be a non-empty string" for field in invalid_fields)
            continue
        if any(character in entry["local_path"] for character in "?#"):
            issues.append(f"source entry {index} local_path must not contain a query or fragment")
            continue
        try:
            local_path = normalise_source_path(source_links_root, entry["local_path"])
        except PathAuthorityError as exc:
            issues.append(f"source entry {index} invalid local_path: {exc}")
            continue
        local_abs = (source_links_root / local_path).resolve()
        if local_abs in seen:
            issues.append(f"duplicate source-link local_path: {local_path}")
            continue
        parsed_url = urlparse(entry["public_url"])
        if (
            parsed_url.scheme != "https" or not parsed_url.netloc
            or parsed_url.username is not None or parsed_url.password is not None
            or parsed_url.fragment
        ):
            issues.append(f"source entry {index} public_url must be an official HTTPS URL without credentials or fragment")
            continue
        if entry["public_origin"] != "official":
            issues.append(f"source entry {index} public_origin must be official")
            continue
        seen.add(local_abs)
        registry.setdefault(local_abs, []).append(SourceLinkEntry(local_path, entry["public_url"]))
    return registry, issues


_REFERENCE_DESTINATION_RE = re.compile(
    r"^(?:<(?P<angle>.*?)#page=(?P<angle_page>-?\d+)>|(?P<bare>.*?)#page=(?P<bare_page>-?\d+))$"
)


def parse_source_link_destination(destination: str) -> tuple[str, int] | None:
    """Parse a reference destination while retaining verifier diagnostics."""
    match = _REFERENCE_DESTINATION_RE.fullmatch(destination)
    if match is None:
        return None
    path = match.group("angle") or match.group("bare") or ""
    page = match.group("angle_page") or match.group("bare_page")
    return path.replace(r"\ ", " "), int(page)


def parse_staged_source_destination(destination: str) -> tuple[str, int] | None:
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
