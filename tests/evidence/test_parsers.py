"""Direct parser unit tests, including one against the static fixture under
``fixtures/`` (most other tests build fixtures inline via ``conftest.py``)."""

from __future__ import annotations

from pathlib import Path

from tracecite.evidence.parsers import markdown as markdown_parser
from tracecite.evidence.parsers import pdf as pdf_parser

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def test_markdown_parser_against_static_fixture():
    result = markdown_parser.parse(FIXTURES_DIR / "sample-report.md")
    heading_texts = [u.text for u in result.units if u.content_type == "heading"]
    assert heading_texts == ["Sample Synthetic Report", "Overview", "Findings", "Conclusion"]

    findings_units = [u for u in result.units if u.heading_path[-1:] == ["Findings"]]
    assert any("synthetic storage capacity" in u.text for u in findings_units)
    assert all(u.line_start is not None for u in result.units)


def test_markdown_units_from_layout_reconstruction_matches_fresh_parse():
    result = markdown_parser.parse(FIXTURES_DIR / "sample-report.md")
    import json

    layout_json = json.dumps(result.pages[0].layout)
    rebuilt = markdown_parser.units_from_page_layout(layout_json)
    assert [u.text for u in rebuilt] == [u.text for u in result.units]
    assert [u.logical_key for u in rebuilt] == [u.logical_key for u in result.units]


def test_pdf_parser_heading_and_body_content_types(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from conftest import build_pdf

    pdf_path = build_pdf(
        tmp_path / "doc.pdf",
        [["Overview", "A short synthetic body paragraph used only for this parser unit test."]],
    )
    result = pdf_parser.parse(pdf_path)
    content_types = {u.content_type for u in result.units}
    assert content_types == {"heading", "body"}
    assert result.pages[0].physical_page == 1


def test_pdf_parser_ocr_fallback_for_no_text_layer_page(tmp_path):
    """A page with a genuinely rasterised, no-text-layer image (built via
    PyMuPDF like every other fixture here, not mocked) must still surface
    plausible text through the OCR fallback (task 0090 item 1), while an
    ordinary text-layer page alongside it is completely unaffected."""

    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from conftest import build_pdf_with_image_only_page

    pdf_path = build_pdf_with_image_only_page(
        tmp_path / "scan.pdf",
        leading_pages=[["Intro", "This is a normal text page used only as a non-OCR control."]],
    )
    result = pdf_parser.parse(pdf_path)
    assert len(result.pages) == 2

    text_page, scanned_page = result.pages
    assert text_page.extraction_method == pdf_parser.NAME
    assert "normal text page" in text_page.text

    assert scanned_page.extraction_method.startswith(f"{pdf_parser.NAME}-ocr-")
    assert scanned_page.extraction_status == "ok"
    assert "text layer" in scanned_page.text.lower()

    scanned_units = [u for u in result.units if u.physical_page == 2]
    assert scanned_units
    assert scanned_units[0].content_type == "body"
    assert "text layer" in scanned_units[0].text.lower()


def test_pdf_parser_short_real_text_page_not_replaced_by_ocr(tmp_path):
    """A page whose genuinely-extracted text happens to be shorter than the
    OCR threshold (e.g. two short one-word headings) still triggers the OCR
    fallback attempt, but since PyMuPDF's OCR of that same real text does
    not come back *longer* than what was already extracted, the original
    blocks/extraction_method must be preserved rather than overwritten with
    a redundant or degraded OCR pass."""

    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from conftest import build_pdf

    pdf_path = build_pdf(tmp_path / "short.pdf", [["Hi", "X"]])
    result = pdf_parser.parse(pdf_path)

    assert result.pages[0].extraction_method == pdf_parser.NAME
    assert result.pages[0].text == "Hi\n\nX"
    assert [u.text for u in result.units] == ["Hi", "X"]


def test_pdf_parser_figure_crop_nearby_text_association(tmp_path):
    """A figure crop's ``nearby_text`` should pick up a caption that sits
    just above the image (task 0090 item 2), reusing the page's
    already-computed text blocks -- not re-implementing block extraction."""

    import fitz

    helper = fitz.open()
    try:
        helper_page = helper.new_page(width=300, height=150)
        helper_page.insert_text((10, 80), "A simple figure", fontsize=18)
        image_bytes = helper_page.get_pixmap(dpi=150).tobytes("png")
    finally:
        helper.close()

    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 90), "Figure 1: Illustrative capacity chart shown below.", fontsize=11)
        page.insert_image(fitz.Rect(72, 110, 372, 260), stream=image_bytes)
        pdf_path = tmp_path / "figure.pdf"
        document.save(pdf_path)
    finally:
        document.close()

    crops = pdf_parser.render_figure_crops(pdf_path, 1)
    assert len(crops) == 1
    assert crops[0].nearby_text is not None
    assert "Figure 1" in crops[0].nearby_text


def test_pdf_parser_tesseract_cli_stage_recovers_text(tmp_path, monkeypatch):
    """The second, last-resort OCR stage genuinely shells out to the
    Tesseract CLI (via ``subprocess.run`` with an argument list) against a
    rendered page image and recovers real text -- exercised here (not
    mocked) by forcing the first PyMuPDF-OCR stage to look insufficient, so
    the fallback to ``_tesseract_cli_ocr_text`` actually runs."""

    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from conftest import build_pdf_with_image_only_page

    pdf_path = build_pdf_with_image_only_page(tmp_path / "scan.pdf")

    monkeypatch.setattr(pdf_parser, "_pymupdf_ocr_text", lambda page, *, lang, dpi: "")

    result = pdf_parser.parse(pdf_path)
    assert result.pages[0].extraction_method == f"{pdf_parser.NAME}-ocr-tesseract-cli"
    assert "text layer" in result.pages[0].text.lower()


def test_pdf_parser_figure_crop_without_nearby_text_is_none(tmp_path):
    """A figure crop with no text anywhere near its bbox must get ``None``,
    not an empty string or an unrelated far-away block."""

    import fitz

    helper = fitz.open()
    try:
        helper_page = helper.new_page(width=300, height=150)
        helper_page.insert_text((10, 80), "A simple figure", fontsize=18)
        image_bytes = helper_page.get_pixmap(dpi=150).tobytes("png")
    finally:
        helper.close()

    document = fitz.open()
    try:
        page = document.new_page(height=800)
        page.insert_text((72, 700), "Unrelated text far below the figure.", fontsize=11)
        page.insert_image(fitz.Rect(72, 80, 372, 230), stream=image_bytes)
        pdf_path = tmp_path / "figure-no-caption.pdf"
        document.save(pdf_path)
    finally:
        document.close()

    crops = pdf_parser.render_figure_crops(pdf_path, 1)
    assert len(crops) == 1
    assert crops[0].nearby_text is None
