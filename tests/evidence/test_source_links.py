"""Schema-v3 source-link registry loader and Markdown/PDF destination parsing."""

from __future__ import annotations

from pathlib import Path

from tracecite.evidence.source_links import (
    SourceLinkEntry,
    load_source_links,
    parse_staged_markdown_destination,
    parse_staged_source_destination,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_schema_v3_entry_loads_with_defaults(tmp_path: Path) -> None:
    registry_path = _write(
        tmp_path / "source-links.toml",
        """schema_version = 3

[[source]]
name = "aemo-isp-2024"
local_path = "sources/aemo/2024-integrated-system-plan.pdf"
public_url = "https://www.aemo.com.au/path/to/2024-integrated-system-plan.pdf"
""",
    )
    (tmp_path / "sources/aemo").mkdir(parents=True)
    (tmp_path / "sources/aemo/2024-integrated-system-plan.pdf").write_bytes(b"%PDF-1.4")

    registry, issues = load_source_links(registry_path, tmp_path)
    assert issues == []
    resolved = (tmp_path / "sources/aemo/2024-integrated-system-plan.pdf").resolve()
    entries = registry[resolved]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.name == "aemo-isp-2024"
    assert entry.local_path == "sources/aemo/2024-integrated-system-plan.pdf"
    assert entry.public_url == "https://www.aemo.com.au/path/to/2024-integrated-system-plan.pdf"
    assert entry.metadata == {}


def test_opaque_nested_metadata_survives_parsing_without_affecting_identity(tmp_path: Path) -> None:
    registry_path = _write(
        tmp_path / "source-links.toml",
        """schema_version = 3

[[source]]
name = "aemo-isp-2024"
local_path = "sources/aemo/2024-integrated-system-plan.pdf"
public_url = "https://www.aemo.com.au/path/to/2024-integrated-system-plan.pdf"

[source.metadata]
bibtex_id = "aemo2024isp"
publisher = "Australian Energy Market Operator"
type = "report"
authors = ["A", "B"]

[source.metadata.nested]
depth = 2
""",
    )
    (tmp_path / "sources/aemo").mkdir(parents=True)
    (tmp_path / "sources/aemo/2024-integrated-system-plan.pdf").write_bytes(b"%PDF-1.4")

    registry, issues = load_source_links(registry_path, tmp_path)
    assert issues == []
    resolved = (tmp_path / "sources/aemo/2024-integrated-system-plan.pdf").resolve()
    entry = registry[resolved][0]
    assert entry.metadata == {
        "bibtex_id": "aemo2024isp",
        "publisher": "Australian Energy Market Operator",
        "type": "report",
        "authors": ["A", "B"],
        "nested": {"depth": 2},
    }
    # Identity and routing fields are unaffected by arbitrary metadata content.
    assert entry.name == "aemo-isp-2024"
    assert entry.local_path == "sources/aemo/2024-integrated-system-plan.pdf"


def test_markdown_to_html_entry_loads(tmp_path: Path) -> None:
    registry_path = _write(
        tmp_path / "source-links.toml",
        """schema_version = 3

[[source]]
name = "tracecite-searchable-evidence"
local_path = "docs/guide/searchable-evidence.md"
public_url = "https://example.org/guide/searchable-evidence/"

[source.metadata]
type = "documentation"
""",
    )
    (tmp_path / "docs/guide").mkdir(parents=True)
    (tmp_path / "docs/guide/searchable-evidence.md").write_text("# Guide\n", encoding="utf-8")

    registry, issues = load_source_links(registry_path, tmp_path)
    assert issues == []
    resolved = (tmp_path / "docs/guide/searchable-evidence.md").resolve()
    entry = registry[resolved][0]
    assert entry.local_path == "docs/guide/searchable-evidence.md"
    assert entry.metadata == {"type": "documentation"}


def test_schema_v2_is_rejected_with_v3_requirement_message(tmp_path: Path) -> None:
    registry_path = _write(
        tmp_path / "source-links.toml",
        """schema_version = 2

[[source]]
title = "Report"
publisher = "Publisher"
local_path = "sources/report.pdf"
public_url = "https://example.invalid/report.pdf"
public_origin = "official"
""",
    )
    registry, issues = load_source_links(registry_path, tmp_path)
    assert registry == {}
    assert len(issues) == 1
    assert "schema_version = 3" in issues[0]


def test_schema_version_missing_is_rejected(tmp_path: Path) -> None:
    registry_path = _write(tmp_path / "source-links.toml", "source = []\n")
    registry, issues = load_source_links(registry_path, tmp_path)
    assert registry == {}
    assert "schema_version = 3" in issues[0]


def test_unknown_source_level_field_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources/report.pdf").write_bytes(b"%PDF-1.4")
    registry_path = _write(
        tmp_path / "source-links.toml",
        """schema_version = 3

[[source]]
name = "report"
local_path = "sources/report.pdf"
publc_url = "https://example.invalid/report.pdf"
""",
    )
    registry, issues = load_source_links(registry_path, tmp_path)
    assert any("unknown field" in issue and "publc_url" in issue for issue in issues)


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    registry_path = _write(
        tmp_path / "source-links.toml",
        """schema_version = 3

[[source]]
local_path = "sources/report.pdf"
public_url = "https://example.invalid/report.pdf"
""",
    )
    registry, issues = load_source_links(registry_path, tmp_path)
    assert any("missing required field" in issue and "name" in issue for issue in issues)


def test_duplicate_names_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources/report.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "sources/report2.pdf").write_bytes(b"%PDF-1.4")
    registry_path = _write(
        tmp_path / "source-links.toml",
        """schema_version = 3

[[source]]
name = "report"
local_path = "sources/report.pdf"
public_url = "https://example.invalid/report.pdf"

[[source]]
name = "report"
local_path = "sources/report2.pdf"
public_url = "https://example.invalid/report2.pdf"
""",
    )
    registry, issues = load_source_links(registry_path, tmp_path)
    assert any("duplicate source-link name" in issue for issue in issues)


def test_duplicate_local_paths_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources/report.pdf").write_bytes(b"%PDF-1.4")
    registry_path = _write(
        tmp_path / "source-links.toml",
        """schema_version = 3

[[source]]
name = "report-a"
local_path = "sources/report.pdf"
public_url = "https://example.invalid/report.pdf"

[[source]]
name = "report-b"
local_path = "./sources/report.pdf"
public_url = "https://example.invalid/report2.pdf"
""",
    )
    registry, issues = load_source_links(registry_path, tmp_path)
    assert any("duplicate" in issue and "local_path" in issue for issue in issues)


def test_unsupported_extension_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources/report.txt").write_text("not routable", encoding="utf-8")
    registry_path = _write(
        tmp_path / "source-links.toml",
        """schema_version = 3

[[source]]
name = "report"
local_path = "sources/report.txt"
public_url = "https://example.invalid/report.txt"
""",
    )
    registry, issues = load_source_links(registry_path, tmp_path)
    assert any(".pdf or .md" in issue for issue in issues)


def test_local_path_with_query_or_fragment_is_rejected(tmp_path: Path) -> None:
    registry_path = _write(
        tmp_path / "source-links.toml",
        """schema_version = 3

[[source]]
name = "report"
local_path = "sources/report.pdf?download=1"
public_url = "https://example.invalid/report.pdf"
""",
    )
    registry, issues = load_source_links(registry_path, tmp_path)
    assert any("query or fragment" in issue for issue in issues)


def test_metadata_must_be_a_table(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources/report.pdf").write_bytes(b"%PDF-1.4")
    registry_path = _write(
        tmp_path / "source-links.toml",
        """schema_version = 3

[[source]]
name = "report"
local_path = "sources/report.pdf"
public_url = "https://example.invalid/report.pdf"
metadata = ["not", "a", "table"]
""",
    )
    registry, issues = load_source_links(registry_path, tmp_path)
    assert any("metadata must be a table" in issue for issue in issues)


def test_public_url_allows_query_string_but_rejects_fragment_and_credentials(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources/report.pdf").write_bytes(b"%PDF-1.4")

    good = _write(
        tmp_path / "good.toml",
        """schema_version = 3

[[source]]
name = "report"
local_path = "sources/report.pdf"
public_url = "https://example.invalid/report.pdf?rev=7&lang=en"
""",
    )
    registry, issues = load_source_links(good, tmp_path)
    assert issues == []
    entry = next(iter(registry.values()))[0]
    assert entry.public_url == "https://example.invalid/report.pdf?rev=7&lang=en"

    for bad_url in (
        "http://example.invalid/report.pdf",
        "https://user:pass@example.invalid/report.pdf",
        "https://example.invalid/report.pdf#page=1",
    ):
        bad = _write(
            tmp_path / "bad.toml",
            f"""schema_version = 3

[[source]]
name = "report"
local_path = "sources/report.pdf"
public_url = "{bad_url}"
""",
        )
        registry, issues = load_source_links(bad, tmp_path)
        assert issues, bad_url


def test_non_empty_string_fields_are_required(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources/report.pdf").write_bytes(b"%PDF-1.4")
    registry_path = _write(
        tmp_path / "source-links.toml",
        """schema_version = 3

[[source]]
name = ""
local_path = "sources/report.pdf"
public_url = "https://example.invalid/report.pdf"
""",
    )
    registry, issues = load_source_links(registry_path, tmp_path)
    assert any("non-empty string" in issue and "name" in issue for issue in issues)


def test_malformed_candidate_entry_reports_table_error(tmp_path: Path) -> None:
    registry_path = _write(
        tmp_path / "source-links.toml",
        """schema_version = 3

source = ["not-a-table"]
""",
    )
    registry, issues = load_source_links(registry_path, tmp_path)
    assert any("must be a table" in issue for issue in issues)


# -- PDF page-fragment destination parsing (unchanged contract) --------------


def test_parse_staged_source_destination_pdf_positive_page(tmp_path: Path) -> None:
    assert parse_staged_source_destination("sources/report.pdf#page=7") == ("sources/report.pdf", 7)
    assert parse_staged_source_destination("sources/report.pdf#page=0") is None
    assert parse_staged_source_destination("sources/report.pdf#page=-1") is None
    assert parse_staged_source_destination("sources/report.md#page=7") is None


# -- Markdown-to-HTML anchor destination parsing -----------------------------


def test_parse_staged_markdown_destination_without_anchor() -> None:
    assert parse_staged_markdown_destination("relative.md") == ("relative.md", "")
    assert parse_staged_markdown_destination("../guide/searchable-evidence.md") == (
        "../guide/searchable-evidence.md",
        "",
    )


def test_parse_staged_markdown_destination_with_anchor() -> None:
    assert parse_staged_markdown_destination("relative.md#overview") == ("relative.md", "overview")
    assert parse_staged_markdown_destination("nested/page.md#section-2") == (
        "nested/page.md",
        "section-2",
    )


def test_parse_staged_markdown_destination_rejects_malformed_candidates() -> None:
    # Query-bearing.
    assert parse_staged_markdown_destination("relative.md?download=1") is None
    assert parse_staged_markdown_destination("relative.md?download=1#overview") is None
    # Remote.
    assert parse_staged_markdown_destination("https://example.invalid/relative.md") is None
    # Angle-wrapped (escaping form), unsupported for narrow Markdown routing.
    assert parse_staged_markdown_destination("<relative.md>") is None
    # Multiple fragments or an empty fragment.
    assert parse_staged_markdown_destination("relative.md#one#two") is None
    assert parse_staged_markdown_destination("relative.md#") is None
    # Wrong extension (including a coincidental ".md" substring).
    assert parse_staged_markdown_destination("relative.mdx") is None
    assert parse_staged_markdown_destination("relative.md5") is None
    assert parse_staged_markdown_destination("relative.pdf") is None
    # Whitespace or forbidden characters in the path or anchor.
    assert parse_staged_markdown_destination("relative with space.md") is None
    assert parse_staged_markdown_destination("relative.md#with space") is None
    assert parse_staged_markdown_destination("relative.md#(parens)") is None
    # Empty destination.
    assert parse_staged_markdown_destination("") is None
