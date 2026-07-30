from __future__ import annotations

import pytest

from tracecite.cli import build_parser as build_root_parser
from tracecite.evidence.cli import build_parser as build_evidence_parser


def test_root_cli_page_selector_is_optional():
    args = build_root_parser().parse_args(["page", "doc.pdf"])
    assert args.page is None


def test_evidence_cli_page_selector_is_optional():
    args = build_evidence_parser().parse_args(["page", "doc.pdf"])
    assert args.page is None


def test_both_parser_surfaces_accept_extract_pages_command(tmp_path):
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    root_args = build_root_parser().parse_args(["extract-pages", "--output-dir", str(output_dir), "doc.pdf"])
    evidence_args = build_evidence_parser().parse_args(["extract-pages", "--output-dir", str(output_dir), "doc.pdf"])
    assert root_args.page is None
    assert evidence_args.page is None


def test_both_parser_surfaces_show_optional_page_selector_in_help(capsys):
    with pytest.raises(SystemExit):
        build_root_parser().parse_args(["page", "--help"])
    root_help = capsys.readouterr().out
    with pytest.raises(SystemExit):
        build_evidence_parser().parse_args(["page", "--help"])
    evidence_help = capsys.readouterr().out
    assert "source_path [page]" in root_help
    assert "--format {text,json}" in root_help
    assert "source_path [page]" in evidence_help
    assert "--format {text,json}" in evidence_help
