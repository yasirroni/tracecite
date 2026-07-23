"""Validated, repository-neutral documentation evidence contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DocsEvidenceContract:
    authored_root: Path
    retained_root: Path
    staged_root: Path
    source_links: Path
    index_output: Path
    publication_exclude: tuple[Path, ...]
    host_render_command: tuple[str, ...] | None = None
