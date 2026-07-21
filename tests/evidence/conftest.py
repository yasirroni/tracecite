"""Shared fixtures: synthetic PDF/Markdown corpora and deterministic embeddings."""

from __future__ import annotations

from pathlib import Path
import tomllib

import fitz
import pytest

from tracecite.evidence import schema, sync as sync_module


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        vectors: list[list[float]] = []
        for text in texts:
            seed = sum((index + 1) * ord(char) for index, char in enumerate(text))
            vector = [0.0] * schema.EMBEDDING_DIMENSIONS
            vector[seed % schema.EMBEDDING_DIMENSIONS] = 1.0
            vector[(seed // 7) % schema.EMBEDDING_DIMENSIONS] = 0.5
            vectors.append(vector)
        return vectors


@pytest.fixture
def make_embedder():
    """Factory for a fresh, call-counting fake embedder."""

    def _make() -> FakeEmbedder:
        return FakeEmbedder()

    return _make


def write_manifest(path: Path, entries: dict[str, str]) -> Path:
    lines = ["schema_version = 1"]
    for relative_path in entries.values():
        lines.extend(["[[source]]", f'path = "{relative_path}"'])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def read_manifest(path: Path) -> dict[str, str]:
    with Path(path).open("rb") as handle:
        data = tomllib.load(handle)
    return {entry["path"]: entry["path"] for entry in data.get("source", [])}


def build_pdf(path: Path, pages: list[list[str]]) -> Path:
    """Build a small synthetic PDF: one paragraph-per-string, per page."""

    document = fitz.open()
    try:
        for paragraphs in pages:
            page = document.new_page()
            y = 72
            for paragraph in paragraphs:
                page.insert_text((72, y), paragraph, fontsize=11)
                y += 20 + 14 * (len(paragraph) // 70)
        path.parent.mkdir(parents=True, exist_ok=True)
        document.save(path)
    finally:
        document.close()
    return path


def build_pdf_with_image_only_page(
    path: Path,
    *,
    image_text: str = "Scanned page with no real text layer at all.",
    leading_pages: list[list[str]] | None = None,
) -> Path:
    """Build a synthetic PDF whose final page has ONLY a rasterised image
    with baked-in text -- no real text layer at all -- so the OCR fallback
    path (task 0090 item 1) is genuinely exercised end-to-end rather than
    unit-tested against a mocked function. Any ``leading_pages`` (same shape
    as :func:`build_pdf`'s ``pages``) come first as ordinary text pages.
    """

    # Rasterise `image_text` on a throwaway page purely to get pixel bytes
    # with baked-in text; this helper document is never saved to disk.
    helper_document = fitz.open()
    try:
        helper_page = helper_document.new_page(width=400, height=200)
        helper_page.insert_text((20, 100), image_text, fontsize=14)
        image_bytes = helper_page.get_pixmap(dpi=200).tobytes("png")
    finally:
        helper_document.close()

    document = fitz.open()
    try:
        for paragraphs in leading_pages or []:
            page = document.new_page()
            y = 72
            for paragraph in paragraphs:
                page.insert_text((72, y), paragraph, fontsize=11)
                y += 20 + 14 * (len(paragraph) // 70)

        # A brand-new page that only ever receives an image insert -- no
        # `insert_text` call at all -- has no text layer whatsoever.
        image_page = document.new_page(width=400, height=200)
        image_page.insert_image(image_page.rect, stream=image_bytes)

        path.parent.mkdir(parents=True, exist_ok=True)
        document.save(path)
    finally:
        document.close()
    return path


def build_markdown(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def corpus_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "sources"
    directory.mkdir()
    return directory


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "runtime" / "knowledge.sqlite"


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    return tmp_path / "sources-manifest.toml"
