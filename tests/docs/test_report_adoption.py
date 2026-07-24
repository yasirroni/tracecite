"""Tests for the real AEMO ISP report adoption example.

These tests exercise ``examples/report-adoption/aemo-isp-comparison`` end to
end (structure, author, staging, index/search/doctor/check, publish-only
isolation, and rendered HTML) by copying the committed example into a
``tmp_path`` fixture, so the committed example and any generated staging or
database artifacts are never mutated by the test run.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tracecite.docs import (
    author_docs,
    check_docs,
    doctor_docs_index,
    load_docs_contract,
    resolve_docs_index_profile,
    search_docs_index,
    sync_docs_index,
)
from tracecite.evidence import schema

EXAMPLE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "report-adoption"
    / "aemo-isp-comparison"
)

CALLOUT_SENTENCE = (
    "This is an illustrative TraceCite adoption example, not production analysis."
)
WEBSITE_CITATION = (
    "https://www.aemo.com.au/energy-systems/major-publications/integrated-system-plan-isp"
)
PUBLIC_2024_URL = (
    "https://www.aemo.com.au/-/media/files/major-publications/isp/2024/"
    "2024-integrated-system-plan-isp.pdf?la=en#page=10"
)
PUBLIC_2026_URL = (
    "https://www.aemo.com.au/-/media/files/major-publications/isp/2026/"
    "2026-integrated-system-plan-isp.pdf?rev=7f5dfd18aa1b4a3aab704c424f75afd3&sc_lang=en#page=76"
)

# Generated/ignored trees that must not be copied into the test fixture: they
# are rebuilt fresh by the test itself, and copying stale copies from a prior
# manual run would make tests depend on leftover local state.
_GENERATED_NAMES = (".quarto", ".tracecite", ".tracecite-stage", "__pycache__", ".git")


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
    def _make() -> FakeEmbedder:
        return FakeEmbedder()

    return _make


def _copy_example(tmp_path: Path, name: str = "copy") -> Path:
    destination = tmp_path / name
    shutil.copytree(
        EXAMPLE_ROOT,
        destination,
        ignore=shutil.ignore_patterns(*_GENERATED_NAMES),
    )
    return destination


def _authored(root: Path):
    config = root / "docs/tracecite.toml"
    contract = load_docs_contract(config, repo_root=root)
    result = author_docs(contract, config_path=config, repo_root=root)
    assert result.ok
    return contract


def _index_snapshot(database_path: Path) -> dict[str, object]:
    # Order by ``logical_key`` (content-derived) rather than the randomly
    # generated ``chunk_id`` UUID: two independent syncs assign different
    # random chunk ids to the same logical chunks, so ordering by chunk_id
    # would make row order (not content) differ between fresh copies.
    conn = schema.connect(database_path)
    try:
        sources = [row["path"] for row in conn.execute("SELECT path FROM sources ORDER BY path")]
        chunks = conn.execute(
            "SELECT logical_key, lexical_hash, semantic_input_hash FROM chunks ORDER BY logical_key"
        ).fetchall()
        return {
            "sources": sources,
            "chunks": [
                {
                    "logical_key": row["logical_key"],
                    "lexical_hash": row["lexical_hash"],
                    "semantic_input_hash": row["semantic_input_hash"],
                }
                for row in chunks
            ],
        }
    finally:
        conn.close()


def _extract_local_destination(text: str, pdf_name: str, page: int) -> str:
    pattern = re.compile(r"\]\(([^)\s]*" + re.escape(f"{pdf_name}#page={page}") + r")\)")
    match = pattern.search(text)
    assert match, f"no local citation destination found for {pdf_name}#page={page}"
    return match.group(1)


def test_report_structure_callout_and_real_pdfs(tmp_path: Path) -> None:
    root = _copy_example(tmp_path)

    expected_files = (
        "README.md",
        "_quarto.yml",
        "docs/tracecite.toml",
        "docs/source-links.toml",
        "docs/authored/report.qmd",
        "docs/retained/report.md",
        "docs/retained/.tracecite-manifest.json",
        "public/report.md",
        "sources/aemo/2024-integrated-system-plan.pdf",
        "sources/aemo/2026-integrated-system-plan.pdf",
        "scripts/render_docs.py",
        "scripts/update_public_snapshot.py",
        "scripts/publish_static.py",
    )
    for relative in expected_files:
        assert (root / relative).is_file(), relative
    assert (root / "static").is_dir()

    authored_text = (root / "docs/authored/report.qmd").read_text(encoding="utf-8")
    retained_text = (root / "docs/retained/report.md").read_text(encoding="utf-8")
    assert "callout-note" in authored_text
    assert CALLOUT_SENTENCE in authored_text
    assert "[!NOTE]" in retained_text
    assert CALLOUT_SENTENCE in retained_text

    lfs_pointer_prefix = b"version https://git-lfs.github.com/spec/v1"
    for relative in (
        "sources/aemo/2024-integrated-system-plan.pdf",
        "sources/aemo/2026-integrated-system-plan.pdf",
    ):
        data = (root / relative).read_bytes()
        assert data[:5] == b"%PDF-"
        assert not data.startswith(lfs_pointer_prefix)


def test_pdfs_are_tracked_through_git_lfs() -> None:
    result = subprocess.run(
        [
            "git",
            "check-attr",
            "filter",
            "--",
            "sources/aemo/2024-integrated-system-plan.pdf",
            "sources/aemo/2026-integrated-system-plan.pdf",
        ],
        cwd=EXAMPLE_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 2
    for relative, line in zip(
        (
            "sources/aemo/2024-integrated-system-plan.pdf",
            "sources/aemo/2026-integrated-system-plan.pdf",
        ),
        lines,
    ):
        assert line == f"{relative}: filter: lfs"


def test_author_renders_retained_with_callout_and_verified_page_citations(tmp_path: Path) -> None:
    root = _copy_example(tmp_path)
    authored_before = (root / "docs/authored/report.qmd").read_bytes()

    contract = _authored(root)
    retained = contract.retained_root / "report.md"
    assert retained.is_file()
    text = retained.read_text(encoding="utf-8")
    assert "[!NOTE]" in text
    assert CALLOUT_SENTENCE in text
    assert "sources/aemo/2024-integrated-system-plan.pdf#page=10" in text
    assert "sources/aemo/2026-integrated-system-plan.pdf#page=76" in text
    assert WEBSITE_CITATION in text

    assert (root / "docs/authored/report.qmd").read_bytes() == authored_before


def test_local_and_public_staging_resolve_correctly_and_preserve_website_citation(
    tmp_path: Path,
) -> None:
    root = _copy_example(tmp_path)
    contract = _authored(root)

    local_path = contract.staged_root / "local" / "report.md"
    public_path = contract.staged_root / "public" / "report.md"
    local_text = local_path.read_text(encoding="utf-8")
    public_text = public_path.read_text(encoding="utf-8")

    for pdf_name, page in (
        ("2024-integrated-system-plan.pdf", 10),
        ("2026-integrated-system-plan.pdf", 76),
    ):
        destination = _extract_local_destination(local_text, pdf_name, page)
        resolved = (local_path.parent / destination.split("#", 1)[0]).resolve()
        assert resolved == (root / "sources/aemo" / pdf_name).resolve()

    assert PUBLIC_2024_URL in public_text
    assert PUBLIC_2026_URL in public_text

    # The website-only citation has no source-links registry row, so it must
    # never be rewritten: identical across retained, local-staged, and
    # public-staged content.
    retained_text = (contract.retained_root / "report.md").read_text(encoding="utf-8")
    assert WEBSITE_CITATION in retained_text
    assert WEBSITE_CITATION in local_text
    assert WEBSITE_CITATION in public_text


def test_author_index_search_doctor_check_succeed_in_order(
    tmp_path: Path, make_embedder
) -> None:
    root = _copy_example(tmp_path)
    contract = _authored(root)

    index_result = sync_docs_index(contract, repo_root=root, embedder=make_embedder())
    assert index_result.sync_report.status == "ok"

    results = search_docs_index(
        contract, "Integrated System Plan", repo_root=root, embedder=make_embedder()
    )
    assert results

    assert doctor_docs_index(contract, repo_root=root) == ()

    check_result = check_docs(
        contract, config_path=root / "docs/tracecite.toml", repo_root=root
    )
    assert check_result.ok


def test_index_input_mirror_excludes_non_report_paths(
    tmp_path: Path, make_embedder
) -> None:
    root = _copy_example(tmp_path)
    contract = _authored(root)
    sync_docs_index(contract, repo_root=root, embedder=make_embedder())

    profile = resolve_docs_index_profile(contract)
    mirrored = {
        path.relative_to(profile.input_root).as_posix()
        for path in profile.input_root.rglob("*")
        if path.is_file()
    }
    assert mirrored == {"report.md"}


def test_two_fresh_copies_are_deterministic_for_sources_and_search(
    tmp_path: Path, make_embedder
) -> None:
    def build_fresh(name: str) -> tuple[dict[str, object], list[dict]]:
        root = _copy_example(tmp_path, name=name)
        config = root / "docs/tracecite.toml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                'index_output = ".tracecite/docs.sqlite"',
                f'index_output = ".tracecite/{name}.sqlite"',
            ),
            encoding="utf-8",
        )
        contract = load_docs_contract(config, repo_root=root)
        author_docs(contract, config_path=config, repo_root=root)
        sync_docs_index(contract, repo_root=root, embedder=make_embedder())
        results = search_docs_index(
            contract, "Integrated System Plan", repo_root=root, embedder=make_embedder()
        )
        return _index_snapshot(contract.index_output), results

    first_snapshot, first_results = build_fresh("fresh-a")
    second_snapshot, second_results = build_fresh("fresh-b")
    assert first_snapshot == second_snapshot
    assert first_results == second_results


def test_publish_static_is_isolated_and_matches_committed_public_snapshot(
    tmp_path: Path,
) -> None:
    root = _copy_example(tmp_path)
    output_dir = tmp_path / "published"

    subprocess.run(
        ["python3", "-S", "scripts/publish_static.py", str(output_dir)],
        cwd=root,
        check=True,
    )

    published = output_dir / "public" / "report.md"
    assert published.is_file()
    assert published.read_bytes() == (EXAMPLE_ROOT / "public" / "report.md").read_bytes()
    assert not (output_dir / "sources").exists()
    assert not (output_dir / "docs").exists()


def test_quarto_rendered_html_contains_callout_and_citation_links(tmp_path: Path) -> None:
    if shutil.which("quarto") is None:
        pytest.skip("quarto not installed")
    root = _copy_example(tmp_path)

    subprocess.run(
        [
            "quarto",
            "render",
            "docs/authored/report.qmd",
            "--to",
            "html",
            "--output",
            "report.html",
        ],
        cwd=root,
        check=True,
    )
    # ``--output`` is resolved relative to the invocation cwd (the Quarto
    # project root), not the input file's directory.
    html = (root / "report.html").read_text(encoding="utf-8")

    assert "callout-note" in html
    assert "Example report" in html
    assert 'href="../../sources/aemo/2024-integrated-system-plan.pdf#page=10"' in html
    assert 'href="../../sources/aemo/2026-integrated-system-plan.pdf#page=76"' in html
    assert f'href="{WEBSITE_CITATION}"' in html
