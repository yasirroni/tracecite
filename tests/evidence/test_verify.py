"""PDF page retrieval, quotation verification, asset validation, and
report/source-links verification tests."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest
from conftest import build_markdown, build_pdf, write_manifest

from tracecite.evidence import schema, verify
from tracecite.evidence import sync as sync_module

# Page renders cost ~1.7 s per sync here; asset storage is owned by
# test_asset_generations.py.
NO_ASSETS = sync_module.SyncOptions(generate_assets=False)


def _index_report_corpus(corpus_dir, manifest_path, database_path, embedder):
    # Build a 65-page-ish document cheaply: just enough pages so page 65 exists.
    pages = [
        ["Section", f"Filler paragraph number {i} for padding purposes only today."]
        for i in range(1, 65)
    ]
    pages.append(
        [
            "Retirement",
            "The retirement trajectory differs between the two planning cycles studied.",
        ]
    )
    build_pdf(corpus_dir / "AEMO_2026_ISP.pdf", pages)
    write_manifest(manifest_path, {"AEMO_2026_ISP.pdf": "AEMO_2026_ISP.pdf"})
    return sync_module.sync(
        corpus_dir, manifest_path, database_path, embedder=embedder, options=NO_ASSETS
    )


def test_verify_quote_exact_and_normalised(
    corpus_dir, manifest_path, database_path, make_embedder
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    with closing(schema.connect(database_path)) as conn:
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

        not_found = verify.verify_quote(
            conn, "AEMO_2026_ISP.pdf", 65, "this text does not appear anywhere"
        )
        assert not_found.status == "not-found"


def test_verify_quote_folds_quote_marks_and_case_but_not_words(
    corpus_dir, manifest_path, database_path, make_embedder
):
    build_markdown(
        corpus_dir / "notice.md",
        "Operators must give two years\u2019 notice and \u201cconsult\u201d first.\n",
    )
    write_manifest(manifest_path, {"notice.md": "notice.md"})
    sync_module.sync(corpus_dir, manifest_path, database_path, embedder=make_embedder())

    def status(quote: str) -> str:
        with closing(schema.connect(database_path)) as conn:
            return verify.verify_quote(conn, "notice.md", 1, quote).status

    assert status("two years\u2019 notice and \u201cconsult\u201d") == "exact"
    assert status('two years\' notice and "consult"') == "normalised"
    assert status("Two Years\u2019 Notice") == "normalised"
    assert status("two months' notice") == "not-found"


def _write_report(report_path: Path, sources_dir: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    relative_pdf = Path("..") / sources_dir.name / "AEMO_2026_ISP.pdf"
    text = f"""The retirement trajectory differs between planning cycles ([2026 ISP, report p. 65][AEMO-2026-ISP-p65]).

> "The retirement trajectory differs between the two planning cycles studied."

- [2026 ISP, report p. 65][AEMO-2026-ISP-p65]

[AEMO-2026-ISP-p65]: {relative_pdf.as_posix()}#page=65
"""
    report_path.write_text(text, encoding="utf-8")


def test_report_citation_and_quote_verification(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "example.md"
    _write_report(report_path, corpus_dir)

    with closing(schema.connect(database_path)) as conn:
        result = verify.verify_report(conn, report_path, corpus_dir)
        assert result.citation_issues == []
        assert result.quote_results
        assert result.quote_results[0].status == "exact"
        assert result.ok


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

    with closing(schema.connect(database_path)) as conn:
        result = verify.verify_report(conn, report_path, corpus_dir)
        assert result.citation_issues == []
        assert result.ok


def test_report_definition_issue_matrix(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
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
    with closing(schema.connect(database_path)) as conn:
        for expected_kind, text in cases.items():
            report_path = tmp_path / "reports" / f"{expected_kind}.md"
            report_path.parent.mkdir(exist_ok=True)
            report_path.write_text(text, encoding="utf-8")
            result = verify.verify_report(conn, report_path, corpus_dir)
            assert not result.ok
            assert any(
                issue.kind == expected_kind for issue in result.citation_issues
            ), (expected_kind, result.citation_issues)


_ENTRY = """
[[source]]
name = "aemo-isp-2026"
local_path = "{local_path}"
public_url = "https://example.invalid/aemo-2026-isp.pdf"
"""


@pytest.mark.parametrize(
    ("local_path", "root", "expected_issue"),
    [
        ("AEMO_2026_ISP.pdf", "evidence", None),
        (None, "evidence", "no source-link entry"),
        ("wrong/path/AEMO_2026_ISP.pdf", "evidence", ""),
        # A distinct registry root matches by canonical absolute path.
        ("{corpus}/AEMO_2026_ISP.pdf", "parent", None),
        ("AEMO_2026_ISP.pdf", "other", "no source-link entry"),
    ],
    ids=["ok", "missing-entry", "wrong-local-path", "distinct-root", "cross-root"],
)
def test_source_links_registry_check_never_mutates_report(
    local_path,
    root,
    expected_issue,
    corpus_dir,
    manifest_path,
    database_path,
    make_embedder,
    tmp_path,
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "example.md"
    _write_report(report_path, corpus_dir)
    original_text = report_path.read_text(encoding="utf-8")
    other_root = tmp_path / "other-root"
    other_root.mkdir()
    (other_root / "AEMO_2026_ISP.pdf").write_text(
        "not the indexed PDF", encoding="utf-8"
    )
    roots = {"evidence": None, "parent": tmp_path, "other": other_root}
    source_links_path = tmp_path / "source-links.toml"
    entry = (
        ""
        if local_path is None
        else _ENTRY.format(local_path=local_path.format(corpus=corpus_dir.name))
    )
    source_links_path.write_text("schema_version = 3\n" + entry, encoding="utf-8")

    with closing(schema.connect(database_path)) as conn:
        result = verify.verify_report(
            conn,
            report_path,
            corpus_dir,
            source_links_path=source_links_path,
            source_links_root=roots[root],
        )
    if expected_issue is None:
        assert result.source_link_issues == []
    else:
        assert any(expected_issue in issue for issue in result.source_link_issues)
    assert report_path.read_text(encoding="utf-8") == original_text


def test_quote_rejects_unrelated_earlier_citation_scope(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "scope.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "[Earlier][A]\n\nA new paragraph with [Later][B].\n\n"
        '> "The retirement trajectory differs between the two planning cycles studied."\n\n'
        "[A]: ../sources/AEMO_2026_ISP.pdf#page=65\n"
        "[B]: ../sources/AEMO_2026_ISP.pdf#page=65\n",
        encoding="utf-8",
    )
    with closing(schema.connect(database_path)) as conn:
        result = verify.verify_report(conn, report_path, corpus_dir)
    assert len(result.quote_results) == 1
    assert result.quote_results[0].status == "exact"
    assert result.quote_results[0].citation_key == "B"


def test_wrapped_citation_paragraph_binds_contiguous_multiline_quote(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "wrapped.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "Evidence [source][A] continues on this physical line.\n"
        "The citation paragraph is wrapped without a blank line.\n\n"
        '> "The retirement trajectory differs between\n'
        '> the two planning cycles studied."\n\n'
        "[A]: ../sources/AEMO_2026_ISP.pdf#page=65\n",
        encoding="utf-8",
    )
    with closing(schema.connect(database_path)) as conn:
        result = verify.verify_report(conn, report_path, corpus_dir)
    assert len(result.quote_results) == 1
    quote = result.quote_results[0]
    assert quote.status == "normalised"
    assert quote.citation_key == "A"
    assert quote.source_path == "AEMO_2026_ISP.pdf"
    assert quote.physical_page == 65


_QUOTE = (
    '> "The retirement trajectory differs between the two planning cycles studied."\n\n'
)
_DEF_A = "[A]: ../sources/AEMO_2026_ISP.pdf#page=65\n"


@pytest.mark.parametrize(
    "body",
    [
        # The citation scope resets at each documented boundary.
        *(
            f"Evidence [source][A].\n\n{transition}\n\n{_QUOTE}{_DEF_A}"
            for transition in (
                "A new paragraph.",
                "# A heading",
                "- a list item",
                "---",
            )
        ),
        # Two viable citation groups are ambiguous.
        (
            f"Evidence cites [one][A] and [two][B].\n\n{_QUOTE}{_DEF_A}"
            "[B]: ../sources/AEMO_2026_ISP.pdf#page=65\n"
        ),
        # Empty and whitespace-only quotes.
        f'Evidence [source][A].\n\n> ""\n\n{_DEF_A}',
        f'Evidence [source][A].\n\n> "   "\n\n{_DEF_A}',
    ],
    ids=["paragraph", "heading", "list", "rule", "two-groups", "empty", "blank"],
)
def test_unbound_or_empty_quotes_fail_structurally(
    body, corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "structural.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(body, encoding="utf-8")
    with closing(schema.connect(database_path)) as conn:
        result = verify.verify_report(conn, report_path, corpus_dir)
    assert [quote.status for quote in result.quote_results] == ["structural-error"]


def test_code_and_comments_are_ignored_by_citation_scanner(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
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
        '> "The retirement trajectory differs between the two planning cycles studied."\n\n'
        "[A]: ../sources/AEMO_2026_ISP.pdf#page=65\n",
        encoding="utf-8",
    )
    with closing(schema.connect(database_path)) as conn:
        result = verify.verify_report(conn, report_path, corpus_dir)
    issue_keys = {issue.key for issue in result.citation_issues}
    assert issue_keys == {"TILDE", "LONG", "SHORT"}
    assert len(result.quote_results) == 1


def test_reference_destinations_accept_spaces_and_angle_brackets(
    corpus_dir, manifest_path, database_path, make_embedder, tmp_path
):
    _index_report_corpus(corpus_dir, manifest_path, database_path, make_embedder())
    report_path = tmp_path / "reports" / "spaces.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        'Evidence [source][A].\n\n> "The retirement trajectory differs between the two planning cycles studied."\n\n'
        "[A]: <../sources/AEMO_2026_ISP.pdf#page=65>\n",
        encoding="utf-8",
    )
    with closing(schema.connect(database_path)) as conn:
        result = verify.verify_report(conn, report_path, corpus_dir)
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
    sync_module.sync(
        corpus_dir,
        manifest_path,
        database_path,
        embedder=make_embedder(),
        options=NO_ASSETS,
    )
    report_path = tmp_path / "reports" / "space-paths.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "Evidence [angle][A].\n\n"
        '> "The retirement trajectory differs between the two planning cycles studied."\n\n'
        "[A]: <../sources/AEMO 2026 ISP.pdf#page=65>\n",
        encoding="utf-8",
    )
    with closing(schema.connect(database_path)) as conn:
        result = verify.verify_report(conn, report_path, corpus_dir)
    assert result.quote_results[0].status == "exact"
    assert result.quote_results[0].source_path == "AEMO 2026 ISP.pdf"

    report_path.write_text(
        "Evidence [escaped][B].\n\n"
        '> "The retirement trajectory differs between the two planning cycles studied."\n\n'
        "[B]: ../sources/AEMO\\ 2026\\ ISP.pdf#page=65\n",
        encoding="utf-8",
    )
    with closing(schema.connect(database_path)) as conn:
        result = verify.verify_report(conn, report_path, corpus_dir)
    assert result.quote_results[0].status == "exact"
    assert result.quote_results[0].source_path == "AEMO 2026 ISP.pdf"
