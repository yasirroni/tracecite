"""PDF page retrieval, quotation verification, asset validation, and
report/source-links verification tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tracecite.evidence import schema, sync as sync_module, verify

from conftest import build_pdf, write_manifest


def _index_report_corpus(corpus_dir, manifest_path, database_path, embedder):
    build_pdf(
        corpus_dir / "AEMO_2026_ISP.pdf",
        [["Front", "Cover page."]] + [["Retirement", "The retirement trajectory differs between planning cycles."]] * 0,
    )
    # Build a 65-page-ish document cheaply: just enough pages so page 65 exists.
    pages = [["Section", f"Filler paragraph number {i} for padding purposes only today."] for i in range(1, 65)]
    pages.append(["Retirement", "The retirement trajectory differs between the two planning cycles studied."])
    build_pdf(corpus_dir / "AEMO_2026_ISP.pdf", pages)
    write_manifest(manifest_path, {"AEMO_2026_ISP.pdf": "AEMO_2026_ISP.pdf"})
    return sync_module.sync(corpus_dir, manifest_path, database_path, embedder=embedder)


def test_pdf_physical_page_retrieval(corpus_dir, manifest_path, database_path, make_embedder):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    conn = schema.connect(database_path)
    try:
        row = conn.execute(
            "SELECT text FROM pages JOIN sources USING (source_pk) WHERE sources.path = 'AEMO_2026_ISP.pdf' AND physical_page = 65"
        ).fetchone()
        assert row is not None
        assert "retirement trajectory" in row["text"].lower()
    finally:
        conn.close()


def test_verify_quote_exact_and_normalised(corpus_dir, manifest_path, database_path, make_embedder):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    conn = schema.connect(database_path)
    try:
        exact = verify.verify_quote(
            conn,
            "AEMO_2026_ISP.pdf",
            65,
            "The retirement trajectory differs between the two planning cycles studied.",
        )
        assert exact.status == "exact"

        normalised = verify.verify_quote(
            conn,
            "AEMO_2026_ISP.pdf",
            65,
            "The   retirement trajectory differs   between the two planning cycles studied.  ",
        )
        assert normalised.status == "normalised"

        not_found = verify.verify_quote(conn, "AEMO_2026_ISP.pdf", 65, "this text does not appear anywhere")
        assert not_found.status == "not-found"
    finally:
        conn.close()


def test_image_and_crop_asset_validation(corpus_dir, manifest_path, database_path, make_embedder):
    report = _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    assert report.sources_added == ["AEMO_2026_ISP.pdf"]
    conn = schema.connect(database_path)
    try:
        rows = conn.execute(
            "SELECT asset_path, asset_type, width, height, assets.sha256 FROM assets "
            "JOIN sources USING (source_pk) WHERE sources.path = 'AEMO_2026_ISP.pdf' AND physical_page = 65"
        ).fetchall()
        assert rows
        render_rows = [r for r in rows if r["asset_type"] == "page-render"]
        assert len(render_rows) == 1
        render = render_rows[0]
        path = schema.resolve_asset_path(database_path, render["asset_path"])
        assert path.is_file()
        assert render["width"] > 0 and render["height"] > 0
        import hashlib

        assert hashlib.sha256(path.read_bytes()).hexdigest() == render["sha256"]
        assert sync_module.integrity_check(conn) == []
    finally:
        conn.close()


def _write_report(report_path: Path, sources_dir: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    relative_pdf = Path("..") / sources_dir.name / "AEMO_2026_ISP.pdf"
    text = f"""The retirement trajectory differs between planning cycles ([2026 ISP, report p. 65][AEMO-2026-ISP-p65]).

> "The retirement trajectory differs between the two planning cycles studied."

- [2026 ISP, report p. 65][AEMO-2026-ISP-p65]

[AEMO-2026-ISP-p65]: {relative_pdf.as_posix()}#page=65
"""
    report_path.write_text(text, encoding="utf-8")


def test_report_citation_and_quote_verification(corpus_dir, manifest_path, database_path, make_embedder, tmp_path):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "example.md"
    _write_report(report_path, corpus_dir)

    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir)
        assert result.citation_issues == []
        assert result.quote_results
        assert result.quote_results[0].status == "exact"
        assert result.ok
    finally:
        conn.close()


def test_report_citation_backslash_path_normalised(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    """A Windows-style backslash-separated reference-definition path resolves to a
    different ``Path`` than the forward-slash path even after ``.resolve()`` (pathlib
    on POSIX treats ``\\`` as a literal filename character, not a separator). This must
    be tolerated via the same backslash-normalising fallback used for the source-links
    check, not flagged as ``bad-path``."""
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "example.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    backslash_pdf_ref = "..\\" + corpus_dir.name + "\\AEMO_2026_ISP.pdf"
    text = f"""The retirement trajectory differs between planning cycles ([2026 ISP, report p. 65][AEMO-2026-ISP-p65]).

> "The retirement trajectory differs between the two planning cycles studied."

- [2026 ISP, report p. 65][AEMO-2026-ISP-p65]

[AEMO-2026-ISP-p65]: {backslash_pdf_ref}#page=65
"""
    report_path.write_text(text, encoding="utf-8")

    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir)
        assert result.citation_issues == []
        assert result.ok
    finally:
        conn.close()


def test_report_verification_flags_bad_citation(corpus_dir, manifest_path, database_path, make_embedder, tmp_path):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "bad.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "See [ref][AEMO-2026-ISP-p9999].\n\n"
        "[AEMO-2026-ISP-p9999]: ../sources/AEMO_2026_ISP.pdf#page=9999\n",
        encoding="utf-8",
    )
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir)
        assert any(issue.kind == "page-not-indexed" for issue in result.citation_issues)
        assert not result.ok
    finally:
        conn.close()


def test_report_definition_issue_matrix(corpus_dir, manifest_path, database_path, make_embedder, tmp_path):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    cases = {
        "missing-definition": "See [ref][missing].\n",
        "malformed-page": "See [ref][bad].\n\n[bad]: ../sources/AEMO_2026_ISP.pdf#page=abc\n",
        "bad-page": "See [ref][zero].\n\n[zero]: ../sources/AEMO_2026_ISP.pdf#page=0\n",
        "unindexed-path": "See [ref][other].\n\n[other]: ../sources/other.pdf#page=1\n",
        "path-outside-root": "See [ref][outside].\n\n[outside]: ../outside.pdf#page=1\n",
        "page-not-indexed": "See [ref][p999].\n\n[p999]: ../sources/AEMO_2026_ISP.pdf#page=999\n",
        "duplicate-definition": "See [ref][dup].\n\n[dup]: ../sources/AEMO_2026_ISP.pdf#page=65\n[dup]: ../sources/AEMO_2026_ISP.pdf#page=65\n",
        "ambiguous-definition": "See [ref][dup].\n\n[dup]: ../sources/AEMO_2026_ISP.pdf#page=65\n[dup]: ../sources/AEMO_2026_ISP.pdf#page=64\n",
    }
    conn = schema.connect(database_path)
    try:
        for expected_kind, text in cases.items():
            report_path = tmp_path / "reports" / f"{expected_kind}.md"
            report_path.parent.mkdir(exist_ok=True)
            report_path.write_text(text, encoding="utf-8")
            result = verify.verify_report(conn, report_path, corpus_dir)
            assert not result.ok
            assert any(issue.kind == expected_kind for issue in result.citation_issues), (expected_kind, result.citation_issues)
    finally:
        conn.close()


def test_source_links_registry_consistency_without_mutating_report(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "example.md"
    _write_report(report_path, corpus_dir)
    original_text = report_path.read_text(encoding="utf-8")

    source_links_path = tmp_path / "source-links.toml"
    source_links_path.write_text(
        """schema_version = 2

[[source]]
title = "2026 Integrated System Plan"
publisher = "Australian Energy Market Operator"
local_path = "AEMO_2026_ISP.pdf"
public_url = "https://example.invalid/aemo-2026-isp.pdf"
public_origin = "official"
""",
        encoding="utf-8",
    )

    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir, source_links_path=source_links_path)
        assert result.source_link_issues == []
    finally:
        conn.close()

    assert report_path.read_text(encoding="utf-8") == original_text  # never mutated

    # Now make the registry inconsistent (missing entry) and confirm it's flagged.
    source_links_path.write_text("schema_version = 2\n", encoding="utf-8")
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir, source_links_path=source_links_path)
        assert result.source_link_issues
    finally:
        conn.close()
    assert report_path.read_text(encoding="utf-8") == original_text


def test_source_links_registry_flags_local_path_mismatch(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "example.md"
    _write_report(report_path, corpus_dir)

    source_links_path = tmp_path / "source-links.toml"
    source_links_path.write_text(
        """schema_version = 2

[[source]]
title = "2026 Integrated System Plan"
publisher = "Australian Energy Market Operator"
local_path = "wrong/path/AEMO_2026_ISP.pdf"
public_url = "https://example.invalid/aemo-2026-isp.pdf"
public_origin = "official"
""",
        encoding="utf-8",
    )

    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir, source_links_path=source_links_path)
        assert result.source_link_issues
        assert result.source_link_issues
    finally:
        conn.close()


def test_source_links_registry_root_distinct_from_evidence_root_matches_by_canonical_absolute_path(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "example.md"
    _write_report(report_path, corpus_dir)
    registry_root = tmp_path
    source_links_path = tmp_path / "source-links.toml"
    source_links_path.write_text(
        f"""schema_version = 2

[[source]]
title = "2026 Integrated System Plan"
publisher = "Australian Energy Market Operator"
local_path = "{corpus_dir.name}/AEMO_2026_ISP.pdf"
public_url = "https://example.invalid/aemo-2026-isp.pdf"
public_origin = "official"
""",
        encoding="utf-8",
    )

    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir, source_links_path=source_links_path, source_links_root=registry_root)
        assert result.source_link_issues == []
    finally:
        conn.close()


def test_source_links_registry_cross_root_mismatch_reports_specific_issue(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "example.md"
    _write_report(report_path, corpus_dir)
    other_root = tmp_path / "other-root"
    other_root.mkdir()
    (other_root / "AEMO_2026_ISP.pdf").write_text("not the indexed PDF", encoding="utf-8")
    source_links_path = tmp_path / "source-links.toml"
    source_links_path.write_text(
        """schema_version = 2

[[source]]
title = "2026 Integrated System Plan"
publisher = "Australian Energy Market Operator"
local_path = "AEMO_2026_ISP.pdf"
public_url = "https://example.invalid/aemo-2026-isp.pdf"
public_origin = "official"
""",
        encoding="utf-8",
    )
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir, source_links_path=source_links_path, source_links_root=other_root)
        assert any("no source-link entry" in issue for issue in result.source_link_issues)
    finally:
        conn.close()


def test_source_links_rejects_legacy_schema_id_missing_fields_and_duplicates(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "example.md"
    _write_report(report_path, corpus_dir)
    source_links_path = tmp_path / "source-links.toml"

    cases = [
        ("schema_version = 1\n", "schema_version = 2"),
        (
            """schema_version = 2

[[source]]
id = "legacy"
title = "Title"
publisher = "Publisher"
local_path = "AEMO_2026_ISP.pdf"
public_url = "https://example.invalid/source.pdf"
public_origin = "official"
""",
            "unknown field",
        ),
        (
            """schema_version = 2

[[source]]
title = "Title"
publisher = "Publisher"
local_path = "AEMO_2026_ISP.pdf"
public_url = "https://example.invalid/source.pdf"
""",
            "missing required field",
        ),
        (
            """schema_version = 2

[[source]]
title = "Title"
publisher = "Publisher"
local_path = "AEMO_2026_ISP.pdf"
public_url = "https://example.invalid/source.pdf"
public_origin = "official"

[[source]]
title = "Duplicate"
publisher = "Publisher"
local_path = "./AEMO_2026_ISP.pdf"
public_url = "https://example.invalid/source2.pdf"
public_origin = "official"
""",
            "duplicate",
        ),
    ]

    conn = schema.connect(database_path)
    try:
        for text, expected in cases:
            source_links_path.write_text(text, encoding="utf-8")
            result = verify.verify_report(conn, report_path, corpus_dir, source_links_path=source_links_path)
            assert any(expected in issue for issue in result.source_link_issues)
    finally:
        conn.close()


def test_source_links_registry_rejects_legacy_id_field(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "example.md"
    _write_report(report_path, corpus_dir)

    source_links_path = tmp_path / "source-links.toml"
    source_links_path.write_text(
        """schema_version = 2

[[source]]
title = "2026 Integrated System Plan"
publisher = "Australian Energy Market Operator"
local_path = "AEMO_2026_ISP.pdf"
public_url = "https://example.invalid/aemo-2026-isp.pdf"
public_origin = "official"

[[source]]
id = "AEMO-2026-ISP"
title = "2026 Integrated System Plan (duplicate)"
publisher = "Australian Energy Market Operator"
local_path = "AEMO_2026_ISP.pdf"
public_url = "https://example.invalid/aemo-2026-isp-2.pdf"
public_origin = "official"
""",
        encoding="utf-8",
    )

    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir, source_links_path=source_links_path)
        assert result.source_link_issues
        assert any("unknown field" in issue and "id" in issue for issue in result.source_link_issues)
    finally:
        conn.close()


def test_quote_rejects_unrelated_earlier_citation_scope(corpus_dir, manifest_path, database_path, make_embedder, tmp_path):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "scope.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "[Earlier][A]\n\nA new paragraph with [Later][B].\n\n"
        "> \"The retirement trajectory differs between the two planning cycles studied.\"\n\n"
        "[A]: ../sources/AEMO_2026_ISP.pdf#page=65\n"
        "[B]: ../sources/AEMO_2026_ISP.pdf#page=65\n",
        encoding="utf-8",
    )
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir)
    finally:
        conn.close()
    assert len(result.quote_results) == 1
    assert result.quote_results[0].status == "exact"
    assert result.quote_results[0].matched_key == "B"


def test_wrapped_citation_paragraph_binds_contiguous_multiline_quote(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "wrapped.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "Evidence [source][A] continues on this physical line.\n"
        "The citation paragraph is wrapped without a blank line.\n\n"
        "> \"The retirement trajectory differs between\n"
        "> the two planning cycles studied.\"\n\n"
        "[A]: ../sources/AEMO_2026_ISP.pdf#page=65\n",
        encoding="utf-8",
    )
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir)
    finally:
        conn.close()
    assert len(result.quote_results) == 1
    quote = result.quote_results[0]
    assert quote.status == "normalised"
    assert quote.matched_key == "A"
    assert quote.source_path == "AEMO_2026_ISP.pdf"
    assert quote.physical_page == 65


@pytest.mark.parametrize(
    "transition",
    ["A new paragraph.", "# A heading", "- a list item", "---"],
)
def test_quote_scope_resets_at_all_documented_boundaries(
    transition, corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "reset.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "Evidence [source][A].\n\n"
        f"{transition}\n\n"
        "> \"The retirement trajectory differs between the two planning cycles studied.\"\n\n"
        "[A]: ../sources/AEMO_2026_ISP.pdf#page=65\n",
        encoding="utf-8",
    )
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir)
    finally:
        conn.close()
    assert [quote.status for quote in result.quote_results] == ["structural-error"]


def test_multiple_viable_citation_groups_fail_structurally(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "ambiguous.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "Evidence cites [one][A] and [two][B].\n\n"
        "> \"The retirement trajectory differs between the two planning cycles studied.\"\n\n"
        "[A]: ../sources/AEMO_2026_ISP.pdf#page=65\n"
        "[B]: ../sources/AEMO_2026_ISP.pdf#page=65\n",
        encoding="utf-8",
    )
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir)
    finally:
        conn.close()
    assert result.quote_results[0].status == "structural-error"


def test_raw_empty_quote_fails_structurally(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "raw-empty.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "Evidence [source][A].\n\n> \"\"\n\n[A]: ../sources/AEMO_2026_ISP.pdf#page=65\n",
        encoding="utf-8",
    )
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir)
    finally:
        conn.close()
    assert result.quote_results[0].status == "structural-error"


def test_whitespace_empty_quote_fails_structurally(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "whitespace-empty.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "Evidence [source][A].\n\n> \"   \"\n\n[A]: ../sources/AEMO_2026_ISP.pdf#page=65\n",
        encoding="utf-8",
    )
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir)
    finally:
        conn.close()
    assert result.quote_results[0].status == "structural-error"


def test_empty_and_whitespace_quotes_fail_structurally(corpus_dir, manifest_path, database_path, make_embedder, tmp_path):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "empty.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "Evidence [A].\n\n> \"\"\n> \"   \"\n\n[A]: ../sources/AEMO_2026_ISP.pdf#page=65\n",
        encoding="utf-8",
    )
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir)
    finally:
        conn.close()
    assert [quote.status for quote in result.quote_results] == ["structural-error"]


def test_code_and_comments_are_ignored_by_citation_scanner(corpus_dir, manifest_path, database_path, make_embedder, tmp_path):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "ignored.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "````python\nHidden [fenced backtick][FB].\n```not-a-closer\n"
        "Still hidden [fenced backtick 2][FB2].\n````   \n\n"
        "~~~python\nHidden [fenced tilde][FT].\n~~~not-a-closer\n"
        "Still hidden [fenced tilde 2][FT2].\n~~~\n\n"
        "    Hidden [indented][I].\n\n"
        "`  Hidden [inline][IC]  `\n\n"
        "~Visible [tilde prose][TILDE]~\n"
        "`Hidden [long closer][LONG]``\n"
        "``Hidden [short closer][SHORT]`\n"
        "<!-- Standalone [single-line comment][SINGLE] -->\n\n"
        "<!-- Hidden [comment][C]\nStill hidden [comment 2][C2] -->\n\n"
        "Evidence [source][A].\n\n"
        "> \"The retirement trajectory differs between the two planning cycles studied.\"\n\n"
        "[A]: ../sources/AEMO_2026_ISP.pdf#page=65\n",
        encoding="utf-8",
    )
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir)
    finally:
        conn.close()
    issue_keys = {issue.key for issue in result.citation_issues}
    assert issue_keys == {"TILDE", "LONG", "SHORT"}
    assert len(result.quote_results) == 1


@pytest.mark.parametrize("field", ["title", "publisher", "local_path", "public_url", "public_origin"])
@pytest.mark.parametrize("value", ["", 7, [], None])
def test_source_link_fields_reject_non_string_and_empty_values(
    field, value, corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "source-links.md"
    report_path.parent.mkdir(parents=True)
    _write_report(report_path, corpus_dir)
    values = {
        "title": "Title", "publisher": "Publisher", "local_path": "AEMO_2026_ISP.pdf",
        "public_url": "https://example.invalid/source.pdf", "public_origin": "official",
    }
    values[field] = value
    source_links_path = tmp_path / "source-links.toml"
    lines = ["schema_version = 2", "", "[[source]]"]
    for key, item in values.items():
        if isinstance(item, str):
            lines.append(f'{key} = "{item}"')
        elif item is None:
            lines.append(f"{key} = 0")
        elif isinstance(item, list):
            lines.append(f"{key} = []")
        else:
            lines.append(f"{key} = {item}")
    source_links_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir, source_links_path=source_links_path)
    finally:
        conn.close()
    assert any(f"{field}" in issue for issue in result.source_link_issues)


def test_reference_destinations_accept_spaces_and_angle_brackets(corpus_dir, manifest_path, database_path, make_embedder, tmp_path):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "spaces.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "Evidence [source][A].\n\n> \"The retirement trajectory differs between the two planning cycles studied.\"\n\n"
        "[A]: <../sources/AEMO_2026_ISP.pdf#page=65>\n",
        encoding="utf-8",
    )
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir)
    finally:
        conn.close()
    assert result.citation_issues == []
    assert result.quote_results[0].status == "exact"


def test_reference_destinations_accept_true_angle_and_escaped_space_paths(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    source = corpus_dir / "AEMO 2026 ISP.pdf"
    source.write_bytes((corpus_dir / "AEMO_2026_ISP.pdf").read_bytes())
    manifest_path.write_text(
        'schema_version = 1\n[[source]]\npath = "AEMO_2026_ISP.pdf"\n'
        '[[source]]\npath = "AEMO 2026 ISP.pdf"\n',
        encoding="utf-8",
    )
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())
    report_path = tmp_path / "reports" / "space-paths.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "Evidence [angle][A].\n\n"
        "> \"The retirement trajectory differs between the two planning cycles studied.\"\n\n"
        "[A]: <../sources/AEMO 2026 ISP.pdf#page=65>\n",
        encoding="utf-8",
    )
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir)
    finally:
        conn.close()
    assert result.quote_results[0].status == "exact"
    assert result.quote_results[0].source_path == "AEMO 2026 ISP.pdf"

    report_path.write_text(
        "Evidence [escaped][B].\n\n"
        "> \"The retirement trajectory differs between the two planning cycles studied.\"\n\n"
        "[B]: ../sources/AEMO\\ 2026\\ ISP.pdf#page=65\n",
        encoding="utf-8",
    )
    conn = schema.connect(database_path)
    try:
        result = verify.verify_report(conn, report_path, corpus_dir)
    finally:
        conn.close()
    assert result.quote_results[0].status == "exact"
    assert result.quote_results[0].source_path == "AEMO 2026 ISP.pdf"


def test_source_links_top_level_source_must_be_array_of_tables(tmp_path):
    source_links_path = tmp_path / "source-links.toml"
    source_links_path.write_text("schema_version = 2\nsource = 42\n", encoding="utf-8")

    registry, issues = verify._load_source_links(source_links_path, tmp_path)

    assert registry == {}
    assert issues == [f"{source_links_path} field source must be an array of tables"]


@pytest.mark.parametrize("local_path", ["AEMO_2026_ISP.pdf?download=1", "AEMO_2026_ISP.pdf#page=65"])
def test_verifier_source_link_loader_rejects_local_path_query_or_fragment(tmp_path, local_path):
    source_links_path = tmp_path / "source-links.toml"
    source_links_path.write_text(
        f'''schema_version = 2

[[source]]
title = "Title"
publisher = "Publisher"
local_path = "{local_path}"
public_url = "https://example.invalid/source.pdf"
public_origin = "official"
''',
        encoding="utf-8",
    )

    registry, issues = verify._load_source_links(source_links_path, tmp_path)

    assert registry == {}
    assert issues == ["source entry 1 local_path must not contain a query or fragment"]
