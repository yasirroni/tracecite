from __future__ import annotations

from pathlib import Path

import pytest

from tracecite.docs import load_docs_contract, stage_docs
from tracecite.evidence.source_links import (
    parse_source_link_destination,
    parse_staged_source_destination,
)
from tracecite.evidence.verify import _parse_definitions
import tracecite.evidence.verify as verify_module


def _fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    (tmp_path / "docs/authored").mkdir(parents=True)
    retained = tmp_path / "docs/retained"
    retained.mkdir()
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources/report.pdf").write_bytes(b"pdf")
    (tmp_path / "docs/source-links.toml").write_text(
        """schema_version = 2

[[source]]
title = "Report"
publisher = "Publisher"
local_path = "sources/report.pdf"
public_url = "https://publisher.example/report.pdf?rev=1"
public_origin = "official"
""",
        encoding="utf-8",
    )
    source = """---
title: "[frontmatter](../../sources/report.pdf#page=12)"
---
# Links

See [report](../../sources/report.pdf#page=3).
Multiple [first](../../sources/report.pdf#page=5) and [second](../../sources/report.pdf#page=6).

[report-page]: ../../sources/report.pdf#page=4
[ordinary]: https://example.invalid/ordinary.pdf

`[code]: ../../sources/report.pdf#page=9`
Use `[code](../../sources/report.pdf#page=11)` literally.

    See [indented](../../sources/report.pdf#page=13).
<!-- See [comment](../../sources/report.pdf#page=14). -->
<div>See [raw](../../sources/report.pdf#page=15).</div>
| See [table](../../sources/report.pdf#page=16) |
Header | Citation
--- | ---
Data | [no-leading-pipe-table](../../sources/report.pdf#page=22)
![image](../../sources/report.pdf#page=17)
<https://publisher.example/report.pdf#page=18>
[query](../../sources/report.pdf?download=1#page=19)
[titled](../../sources/report.pdf#page=20 "title")

```md
[fenced]: ../../sources/report.pdf#page=10
```
"""
    (retained / "index.md").write_text(source, encoding="utf-8")
    config = tmp_path / "docs/tracecite.toml"
    config.write_text(
        """schema_version = 1
[docs]
authored_root = "docs/authored"
retained_root = "docs/retained"
staged_root = "docs/.tracecite-stage"
source_links = "docs/source-links.toml"
index_output = ".tracecite/docs/tracecite.sqlite"
publication_exclude = []
""",
        encoding="utf-8",
    )
    return config, retained / "index.md", source


def test_verifier_and_stager_share_destination_parser_contract() -> None:
    destination = "<sources/report\\ file.pdf#page=7>"
    assert parse_source_link_destination(destination) == ("sources/report file.pdf", 7)
    definitions, issues, _ = _parse_definitions(
        [f"[report]: {destination}"]
    )
    assert issues == []
    assert definitions["report"].path == "sources/report file.pdf"
    assert definitions["report"].page == 7
    assert parse_staged_source_destination("sources/report.pdf#page=7") == (
        "sources/report.pdf", 7
    )
    assert parse_staged_source_destination("sources/report.pdf#page=0") is None


def test_verifier_delegates_definition_parsing_at_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def delegated(destination: str) -> tuple[str, int]:
        calls.append(destination)
        return "delegated.pdf", 42

    monkeypatch.setattr(verify_module, "parse_source_link_destination", delegated)
    definitions, issues, _ = _parse_definitions(["[report]: original.pdf#page=7"])

    assert calls == ["original.pdf#page=7"]
    assert issues == []
    assert definitions["report"].path == "delegated.pdf"
    assert definitions["report"].page == 42


def test_stage_local_and_public_rewrite_only_targeted_links(tmp_path: Path) -> None:
    config_path, retained_file, original = _fixture(tmp_path)
    contract = load_docs_contract(config_path, repo_root=tmp_path)

    local = stage_docs(contract, target="local", repo_root=tmp_path)
    local_text = (local.staged_root / "index.md").read_text(encoding="utf-8")
    assert "../../../sources/report.pdf#page=3" in local_text
    assert "../../../sources/report.pdf#page=4" in local_text
    assert "../../../sources/report.pdf#page=5" in local_text
    assert "../../../sources/report.pdf#page=6" in local_text
    assert "https://example.invalid/ordinary.pdf" in local_text
    assert "[fenced]: ../../sources/report.pdf#page=10" in local_text
    assert "`[code]: ../../sources/report.pdf#page=9`" in local_text
    assert "`[code](../../sources/report.pdf#page=11)`" in local_text
    for page in (12, 13, 14, 15, 16, 17):
        assert f"../../sources/report.pdf#page={page}" in local_text
    assert "../../sources/report.pdf#page=22" in local_text
    assert "<https://publisher.example/report.pdf#page=18>" in local_text
    assert "[query](../../sources/report.pdf?download=1#page=19)" in local_text
    assert '[titled](../../sources/report.pdf#page=20 "title")' in local_text

    public = stage_docs(contract, target="public", repo_root=tmp_path)
    public_text = (public.staged_root / "index.md").read_text(encoding="utf-8")
    assert "https://publisher.example/report.pdf?rev=1#page=3" in public_text
    assert "https://publisher.example/report.pdf?rev=1#page=4" in public_text
    assert retained_file.read_text(encoding="utf-8") == original
    assert (contract.staged_root / "local/index.md").is_file()


def test_protected_markdown_constructs_are_preserved_byte_for_byte(tmp_path: Path) -> None:
    config_path, _, original = _fixture(tmp_path)
    contract = load_docs_contract(config_path, repo_root=tmp_path)
    result = stage_docs(contract, target="public", repo_root=tmp_path)
    staged = (result.staged_root / "index.md").read_text(encoding="utf-8")

    protected = [
        'title: "[frontmatter](../../sources/report.pdf#page=12)"',
        "`[code]: ../../sources/report.pdf#page=9`",
        "Use `[code](../../sources/report.pdf#page=11)` literally.",
        "    See [indented](../../sources/report.pdf#page=13).",
        "<!-- See [comment](../../sources/report.pdf#page=14). -->",
        "<div>See [raw](../../sources/report.pdf#page=15).</div>",
        "| See [table](../../sources/report.pdf#page=16) |",
        "Header | Citation",
        "--- | ---",
        "Data | [no-leading-pipe-table](../../sources/report.pdf#page=22)",
        "![image](../../sources/report.pdf#page=17)",
        "<https://publisher.example/report.pdf#page=18>",
        "[query](../../sources/report.pdf?download=1#page=19)",
        '[titled](../../sources/report.pdf#page=20 "title")',
        "[fenced]: ../../sources/report.pdf#page=10",
    ]
    for line in protected:
        assert line in staged
    assert "https://publisher.example/report.pdf?rev=1#page=3" in staged
    assert original.splitlines()[0] in staged


def test_later_thematic_break_is_not_frontmatter(tmp_path: Path) -> None:
    config_path, retained_file, _ = _fixture(tmp_path)
    retained_file.write_text(
        "# Heading\n\n---\n\nSee [report](../../sources/report.pdf#page=21).\n",
        encoding="utf-8",
    )
    contract = load_docs_contract(config_path, repo_root=tmp_path)
    result = stage_docs(contract, target="public", repo_root=tmp_path)
    assert "https://publisher.example/report.pdf?rev=1#page=21" in (
        result.staged_root / "index.md"
    ).read_text(encoding="utf-8")


def test_eligible_links_outside_inline_html_and_comments_are_rewritten(tmp_path: Path) -> None:
    config_path, retained_file, _ = _fixture(tmp_path)
    retained_file.write_text(
        '<span>[raw](../../sources/report.pdf#page=30)</span> '
        'and [eligible](../../sources/report.pdf#page=31)\n'
        '<!-- [comment](../../sources/report.pdf#page=32) --> '
        'and [eligible-too](../../sources/report.pdf#page=33)\n',
        encoding="utf-8",
    )
    contract = load_docs_contract(config_path, repo_root=tmp_path)
    result = stage_docs(contract, target="public", repo_root=tmp_path)
    text = (result.staged_root / "index.md").read_text(encoding="utf-8")

    assert "[raw](../../sources/report.pdf#page=30)" in text
    assert "[comment](../../sources/report.pdf#page=32)" in text
    assert "https://publisher.example/report.pdf?rev=1#page=31" in text
    assert "https://publisher.example/report.pdf?rev=1#page=33" in text


def test_multiline_raw_html_block_is_protected_until_closing_tag(tmp_path: Path) -> None:
    config_path, retained_file, _ = _fixture(tmp_path)
    retained_file.write_text(
        "<div>\n"
        "[raw-block](../../sources/report.pdf#page=34)\n"
        "</div>\n"
        "See [eligible](../../sources/report.pdf#page=35).\n",
        encoding="utf-8",
    )
    contract = load_docs_contract(config_path, repo_root=tmp_path)
    result = stage_docs(contract, target="public", repo_root=tmp_path)
    text = (result.staged_root / "index.md").read_text(encoding="utf-8")

    assert "[raw-block](../../sources/report.pdf#page=34)" in text
    assert "https://publisher.example/report.pdf?rev=1#page=35" in text


def test_multiline_html_comment_is_protected_until_closing_marker(tmp_path: Path) -> None:
    config_path, retained_file, _ = _fixture(tmp_path)
    retained_file.write_text(
        "<!--\n"
        "[comment](../../sources/report.pdf#page=36)\n"
        "-->\n"
        "See [eligible](../../sources/report.pdf#page=37).\n",
        encoding="utf-8",
    )
    contract = load_docs_contract(config_path, repo_root=tmp_path)
    result = stage_docs(contract, target="public", repo_root=tmp_path)
    text = (result.staged_root / "index.md").read_text(encoding="utf-8")

    assert "[comment](../../sources/report.pdf#page=36)" in text
    assert "https://publisher.example/report.pdf?rev=1#page=37" in text


@pytest.mark.parametrize("field_value", ["sources/report.pdf?download=1", "sources/report.pdf#page=2"])
def test_registry_rejects_local_path_query_or_fragment(
    tmp_path: Path, field_value: str
) -> None:
    config_path, _, _ = _fixture(tmp_path)
    registry = tmp_path / "docs/source-links.toml"
    registry.write_text(
        registry.read_text(encoding="utf-8").replace(
            "sources/report.pdf", field_value
        ),
        encoding="utf-8",
    )
    contract = load_docs_contract(config_path, repo_root=tmp_path)
    with pytest.raises(ValueError, match="query or fragment"):
        stage_docs(contract, target="local", repo_root=tmp_path)


def test_stage_failure_preserves_previous_target_and_siblings(tmp_path: Path) -> None:
    config_path, retained_file, _ = _fixture(tmp_path)
    contract = load_docs_contract(config_path, repo_root=tmp_path)
    stage_docs(contract, target="local", repo_root=tmp_path)
    public_root = contract.staged_root / "public"
    public_root.mkdir(parents=True)
    (public_root / "sentinel.md").write_text("previous", encoding="utf-8")
    sibling = contract.staged_root / "unrelated"
    sibling.mkdir()
    (sibling / "keep.txt").write_text("keep", encoding="utf-8")
    retained_file.write_text(
        "See [bad](../../sources/missing.pdf#page=0).\n", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        stage_docs(contract, target="public", repo_root=tmp_path)
    assert (public_root / "sentinel.md").read_text(encoding="utf-8") == "previous"
    assert (contract.staged_root / "local/index.md").is_file()
    assert (sibling / "keep.txt").read_text(encoding="utf-8") == "keep"
