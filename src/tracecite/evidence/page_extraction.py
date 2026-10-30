from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from .page_selection import PageSelectionSyntaxError, PageSelectionUnavailableError, resolve_page_selection
from .paths import PathAuthorityError, file_sha256, normalise_source_path, source_row_for_path


class PageExtractionError(ValueError):
    pass


class PageExtractionMissingError(PageExtractionError):
    """The source or a selected page is not indexed or not on disk."""


@dataclass(frozen=True)
class PageExtractionResult:
    pdf_path: Path
    manifest_path: Path
    normalized_pages: list[int]


def _slugify(text: str, *, limit: int = 24) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip(".-_")
    return (slug or "source")[:limit]


def _selector_token(selector: str | None, normalized_pages: list[int]) -> str:
    raw = selector if selector is not None else "1"
    return hashlib.sha256(f"{raw}|{','.join(map(str, normalized_pages))}".encode("utf-8")).hexdigest()[:12]


def _bounded_name(source_stem: str, selector: str | None, normalized_pages: list[int], suffix: str) -> str:
    base = f"tracecite-extract-{_slugify(source_stem)}-{_selector_token(selector, normalized_pages)}"
    return f"{base[:72]}{suffix}"


def _ensure_real_output_dir(output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    if not output_dir.exists() or not output_dir.is_dir():
        raise PageExtractionError(f"output directory does not exist: {output_dir}")
    if output_dir.is_symlink():
        raise PageExtractionError(f"output directory must not be a symlink: {output_dir}")
    return output_dir.resolve()


def promote_staged_outputs(staged_pdf: Path, staged_manifest: Path, final_pdf: Path, final_manifest: Path) -> None:
    reserved: list[Path] = []
    try:
        for final_path in (final_pdf, final_manifest):
            try:
                descriptor = os.open(final_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as exc:
                raise PageExtractionError(f"output already exists: {final_path}") from exc
            else:
                os.close(descriptor)
                reserved.append(final_path)
        os.replace(staged_pdf, final_pdf)
        os.replace(staged_manifest, final_manifest)
    except Exception:
        for final_path in reserved:
            final_path.unlink(missing_ok=True)
        raise


def extract_pages(
    conn,
    root: Path,
    source_path_input: str,
    selector: str | None,
    output_dir: Path,
) -> PageExtractionResult:
    try:
        source_path = normalise_source_path(root, source_path_input)
    except PathAuthorityError as exc:
        raise PageExtractionError(str(exc)) from exc

    source_row = source_row_for_path(conn, source_path)
    if source_row is None:
        raise PageExtractionMissingError(f"source not found: {source_path}")
    if source_row["source_type"] != "pdf":
        raise PageExtractionError(f"source is not a pdf: {source_path}")

    available_pages = [row["physical_page"] for row in conn.execute("SELECT physical_page FROM pages WHERE source_pk = ? ORDER BY physical_page", (source_row["source_pk"],)).fetchall()]
    if not available_pages:
        raise PageExtractionMissingError(f"no indexed pages for source: {source_path}")

    try:
        normalized_pages = resolve_page_selection(selector, available_pages)
    except PageSelectionSyntaxError as exc:
        raise PageExtractionError(str(exc)) from exc
    except PageSelectionUnavailableError as exc:
        raise PageExtractionMissingError(f"page {exc.page} not indexed for source: {source_path}") from exc

    output_dir_resolved = _ensure_real_output_dir(output_dir)
    root_resolved = root.resolve()
    if (
        output_dir_resolved == root_resolved
        or output_dir_resolved.is_relative_to(root_resolved)
        or root_resolved.is_relative_to(output_dir_resolved)
    ):
        raise PageExtractionError(f"output directory overlaps source root: {output_dir}")
    source_pdf = root / source_path
    if not source_pdf.is_file():
        raise PageExtractionMissingError(f"source pdf missing: {source_path}")
    source_pdf_resolved = source_pdf.resolve()
    source_sha256 = file_sha256(source_pdf_resolved)
    if source_sha256 != source_row["sha256"]:
        raise PageExtractionError(f"source pdf changed since indexing: {source_path}")

    import pymupdf

    with pymupdf.open(source_pdf_resolved) as document:
        if document.page_count < max(normalized_pages):
            raise PageExtractionError(
                f"source pdf has only {document.page_count} page(s), cannot satisfy selection {normalized_pages}"
            )

        pdf_name = _bounded_name(Path(source_path).stem, selector, normalized_pages, ".pdf")
        manifest_name = _bounded_name(Path(source_path).stem, selector, normalized_pages, ".json")
        final_pdf = output_dir_resolved / pdf_name
        final_manifest = output_dir_resolved / manifest_name
        if final_pdf.exists() or final_manifest.exists():
            raise PageExtractionError(f"output already exists: {final_pdf if final_pdf.exists() else final_manifest}")

        with TemporaryDirectory(dir=output_dir_resolved.parent) as temp_root:
            staged_pdf = Path(temp_root) / pdf_name
            staged_manifest = Path(temp_root) / manifest_name
            with pymupdf.open() as derivative:
                for page in normalized_pages:
                    derivative.insert_pdf(document, from_page=page - 1, to_page=page - 1)
                derivative.save(staged_pdf)
            manifest = {
                "schema_version": 1,
                "source_path": source_path,
                "original_selector": selector,
                "selector": selector if selector is not None else "1",
                "normalized_pages": normalized_pages,
                "page_count": len(normalized_pages),
                "source_page_count": document.page_count,
                "source_sha256": source_sha256,
                "derivative_filename": pdf_name,
                "derivative_sha256": file_sha256(staged_pdf),
                "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            staged_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            promote_staged_outputs(staged_pdf, staged_manifest, final_pdf, final_manifest)

    return PageExtractionResult(final_pdf, final_manifest, normalized_pages)
