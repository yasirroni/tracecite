"""PyMuPDF-backed PDF parser: page-, block-, and layout-aware extraction.

All PyMuPDF interaction (text extraction, page rendering, image crops) is
kept behind this module so the database and command contracts never depend
on the specific PDF backend (plan 0006: "Keep it behind the parser interface
so another parser can be evaluated later without changing the database or
command contracts.").
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
import tempfile

import fitz

from .base import ParsedAsset, ParsedChunkUnit, ParsedPage, ParseResult

NAME = "pdf-pymupdf"
VERSION = "1"
HEADING_MAX_CHARS = 70

# A page whose normally-extracted text falls below this many characters is
# treated as effectively text-less (e.g. a scanned/rasterised page with no
# real text layer) and routed through the two-stage OCR fallback below. 20
# was chosen to match the nem-knowledge prototype this behaviour is ported
# from: short enough that legitimate near-blank pages (e.g. a title page
# with just a heading) are not misdiagnosed as scans, but well above the
# handful of stray characters PyMuPDF sometimes extracts from a purely
# rasterised page's invisible metadata.
MIN_EXTRACTED_TEXT_CHARS = 20
DEFAULT_OCR_LANG = "eng"
OCR_DPI = 300
TESSERACT_CMD = "tesseract"

# Nearby-text association for figure crops (item 2): a text block is
# considered "nearby" a crop if it overlaps horizontally (with some
# tolerance, since a caption is often centered/narrower than the image it
# describes) and sits within this many PDF points above or below the
# crop's bounding box. 72pt (1 inch) is a generous but bounded
# caption/label distance -- enough to catch a caption directly above or
# below a figure without pulling in unrelated body text further down the
# page.
NEARBY_TEXT_MAX_VERTICAL_DISTANCE = 72.0
NEARBY_TEXT_HORIZONTAL_TOLERANCE = 20.0


@dataclass(frozen=True)
class RenderedAsset:
    physical_page: int
    asset_type: str
    image_bytes: bytes
    ext: str
    width: int
    height: int
    bbox: tuple[float, float, float, float] | None
    label: str | None = None
    caption: str | None = None
    nearby_text: str | None = None


def _looks_like_heading(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > HEADING_MAX_CHARS:
        return False
    if stripped.endswith((".", ",", ";")):
        return False
    return True


def _blocks_for_page(page: fitz.Page) -> list[dict]:
    raw_blocks = page.get_text("blocks")
    text_blocks = [b for b in raw_blocks if b[6] == 0 and b[4].strip()]
    text_blocks.sort(key=lambda b: (round(b[1], 1), round(b[0], 1)))

    blocks: list[dict] = []
    heading_path: list[str] = []
    offset = 0
    for block in text_blocks:
        x0, y0, x1, y1, text, _block_no, _block_type = block
        text = text.strip()
        is_heading = _looks_like_heading(text)
        if is_heading:
            heading_path = [text]
        start = offset
        end = start + len(text)
        offset = end + 2  # matches the "\n\n" join used to build page text
        blocks.append(
            {
                "text": text,
                "bbox": [x0, y0, x1, y1],
                "heading_path": list(heading_path),
                "content_type": "heading" if is_heading else "body",
                "start_offset": start,
                "end_offset": end,
            }
        )
    return blocks


def _nearby_text_for_bbox(
    blocks: list[dict],
    bbox: tuple[float, float, float, float],
    *,
    max_vertical_distance: float = NEARBY_TEXT_MAX_VERTICAL_DISTANCE,
    horizontal_tolerance: float = NEARBY_TEXT_HORIZONTAL_TOLERANCE,
) -> str | None:
    """Find text blocks (from the page's already-computed
    :func:`_blocks_for_page` output) vertically close to a figure crop's
    bbox -- typically a caption directly above or below the figure -- and
    join their text in reading order. Returns ``None`` if nothing qualifies.
    """

    x0, _y0, x1, _y1 = bbox
    matches: list[tuple[float, str]] = []
    for block in blocks:
        bx0, by0, bx1, by1 = block["bbox"]
        horizontally_overlaps = (
            bx0 <= x1 + horizontal_tolerance and bx1 >= x0 - horizontal_tolerance
        )
        if not horizontally_overlaps:
            continue
        if by1 < bbox[1]:
            vertical_distance = bbox[1] - by1
        elif by0 > bbox[3]:
            vertical_distance = by0 - bbox[3]
        else:
            vertical_distance = 0.0
        if vertical_distance <= max_vertical_distance:
            matches.append((by0, block["text"]))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    return "\n".join(text for _, text in matches)


def _pymupdf_ocr_text(page: fitz.Page, *, lang: str, dpi: int) -> str:
    """First OCR fallback stage: PyMuPDF's own built-in OCR support."""

    try:
        textpage = page.get_textpage_ocr(
            flags=fitz.TEXTFLAGS_TEXT | fitz.TEXT_PRESERVE_WHITESPACE,
            language=lang,
            dpi=dpi,
            full=True,
        )
        return page.get_text("text", textpage=textpage).strip()
    except (RuntimeError, OSError):
        # PyMuPDF's OCR path raises if Tesseract/tessdata is not resolvable
        # in this environment; treat that as "no text", not a hard failure,
        # so the caller can still try the Tesseract-CLI stage.
        return ""


def _tesseract_cli_ocr_text(page: fitz.Page, *, lang: str, dpi: int) -> str:
    """Second, last-resort OCR fallback stage: shell out to the Tesseract
    CLI against a rendered page image.

    Always invoked via ``subprocess.run`` with an explicit argument list --
    never ``shell=True`` and never a string-interpolated command.
    """

    pixmap = page.get_pixmap(dpi=dpi)
    with tempfile.TemporaryDirectory() as tmp_dir:
        image_path = Path(tmp_dir) / "page.png"
        pixmap.save(str(image_path))
        try:
            result = subprocess.run(
                [TESSERACT_CMD, str(image_path), "stdout", "-l", lang],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return ""
    return result.stdout.strip()


def _ocr_fallback_text(page: fitz.Page, *, lang: str, dpi: int) -> tuple[str, str]:
    """Two-stage OCR fallback for a page whose normal text extraction came
    back effectively empty: try PyMuPDF's built-in OCR first, and only if
    that still returns too little text, fall back to the Tesseract CLI.

    Returns ``(text, extraction_method)`` so the caller can record which
    stage (if any) actually produced usable text.
    """

    pymupdf_text = _pymupdf_ocr_text(page, lang=lang, dpi=dpi)
    if len(pymupdf_text) >= MIN_EXTRACTED_TEXT_CHARS:
        return pymupdf_text, f"{NAME}-ocr-pymupdf"

    tesseract_text = _tesseract_cli_ocr_text(page, lang=lang, dpi=dpi)
    if len(tesseract_text) > len(pymupdf_text):
        return tesseract_text, f"{NAME}-ocr-tesseract-cli"
    return pymupdf_text, f"{NAME}-ocr-pymupdf"


def parse(path: Path, config: dict | None = None) -> ParseResult:
    config = config or {}
    ocr_lang = config.get("ocr_lang", DEFAULT_OCR_LANG)
    pages: list[ParsedPage] = []
    units: list[ParsedChunkUnit] = []
    assets: list[ParsedAsset] = []

    with fitz.open(path) as document:
        for index, page in enumerate(document):
            physical_page = index + 1
            blocks = _blocks_for_page(page)
            page_text = "\n\n".join(block["text"] for block in blocks)
            extraction_method = NAME

            if len(page_text.strip()) < MIN_EXTRACTED_TEXT_CHARS:
                ocr_text, ocr_method = _ocr_fallback_text(page, lang=ocr_lang, dpi=OCR_DPI)
                ocr_text = ocr_text.strip()
                if len(ocr_text) > len(page_text.strip()):
                    page_rect = page.rect
                    blocks = [
                        {
                            "text": ocr_text,
                            "bbox": [page_rect.x0, page_rect.y0, page_rect.x1, page_rect.y1],
                            "heading_path": [],
                            "content_type": "body",
                            "start_offset": 0,
                            "end_offset": len(ocr_text),
                        }
                    ]
                    page_text = ocr_text
                    extraction_method = ocr_method

            section_candidates = [b["text"] for b in blocks if b["content_type"] == "heading"]

            pages.append(
                ParsedPage(
                    physical_page=physical_page,
                    printed_label=None,
                    text=page_text,
                    extraction_method=extraction_method,
                    extraction_status="ok" if blocks else "empty",
                    section_candidates=section_candidates,
                    layout={"blocks": blocks},
                )
            )

            for block_index, block in enumerate(blocks):
                units.append(
                    ParsedChunkUnit(
                        text=block["text"],
                        logical_key=f"page{physical_page:04d}-block{block_index:03d}",
                        heading_path=block["heading_path"],
                        symbol=None,
                        content_type=block["content_type"],
                        physical_page=physical_page,
                        page_start_offset=block["start_offset"],
                        page_end_offset=block["end_offset"],
                        page_range_start=physical_page,
                        page_range_end=physical_page,
                        locator={"bbox": block["bbox"]},
                    )
                )

            for image_index, image in enumerate(page.get_images(full=True)):
                xref = image[0]
                rects = page.get_image_rects(xref)
                bbox = tuple(rects[0]) if rects else None
                assets.append(
                    ParsedAsset(
                        physical_page=physical_page,
                        asset_type="figure-crop",
                        bbox=bbox,
                        label=f"page-{physical_page:03d}-image-{image_index:02d}",
                    )
                )

    return ParseResult(pages=pages, units=units, assets=assets)


def units_from_page_layout(source_path: str, physical_page: int, layout_json: str) -> list[ParsedChunkUnit]:
    """Rebuild chunk-input units from retained ``pages.layout_json``.

    Used for a chunker- or normalisation-only change so PyMuPDF is never
    reopened when the retained page extraction is still valid (plan 0006:
    "Do not reopen PDFs merely because the chunker or embedding model
    changed if retained page extraction is sufficient.").
    """

    layout = json.loads(layout_json) if layout_json else {"blocks": []}
    units: list[ParsedChunkUnit] = []
    for block_index, block in enumerate(layout.get("blocks", [])):
        units.append(
            ParsedChunkUnit(
                text=block["text"],
                logical_key=f"page{physical_page:04d}-block{block_index:03d}",
                heading_path=block["heading_path"],
                symbol=None,
                content_type=block["content_type"],
                physical_page=physical_page,
                page_start_offset=block["start_offset"],
                page_end_offset=block["end_offset"],
                page_range_start=physical_page,
                page_range_end=physical_page,
                locator={"bbox": block["bbox"]},
            )
        )
    return units


def render_page(path: Path, physical_page: int, zoom: float = 2.0) -> RenderedAsset:
    with fitz.open(path) as document:
        page = document[physical_page - 1]
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix)
        return RenderedAsset(
            physical_page=physical_page,
            asset_type="page-render",
            image_bytes=pixmap.tobytes("png"),
            ext="png",
            width=pixmap.width,
            height=pixmap.height,
            bbox=None,
        )


def render_figure_crops(path: Path, physical_page: int) -> list[RenderedAsset]:
    rendered: list[RenderedAsset] = []
    with fitz.open(path) as document:
        page = document[physical_page - 1]
        blocks = _blocks_for_page(page)
        for image_index, image in enumerate(page.get_images(full=True)):
            xref = image[0]
            info = document.extract_image(xref)
            rects = page.get_image_rects(xref)
            bbox = tuple(rects[0]) if rects else None
            nearby_text = _nearby_text_for_bbox(blocks, bbox) if bbox is not None else None
            rendered.append(
                RenderedAsset(
                    physical_page=physical_page,
                    asset_type="figure-crop",
                    image_bytes=info["image"],
                    ext=info["ext"],
                    width=info.get("width", 0),
                    height=info.get("height", 0),
                    bbox=bbox,
                    label=f"page-{physical_page:03d}-image-{image_index:02d}",
                    nearby_text=nearby_text,
                )
            )
    return rendered
