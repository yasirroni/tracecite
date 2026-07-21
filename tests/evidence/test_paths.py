from __future__ import annotations

import pytest

from tracecite.evidence.paths import PathAuthorityError, normalise_source_path


def test_normalise_source_path_accepts_equivalent_relative_and_report_based_paths(tmp_path):
    root = tmp_path / "root"
    docs = root / "docs"
    docs.mkdir(parents=True)
    source = docs / "report.md"
    source.write_text("body", encoding="utf-8")
    report_dir = root / "reports"
    report_dir.mkdir()

    assert normalise_source_path(root, "docs/./report.md") == "docs/report.md"
    assert normalise_source_path(root, "../docs/report.md", base=report_dir) == "docs/report.md"


def test_normalise_source_path_rejects_traversal_absolute_outside_and_symlink_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("body", encoding="utf-8")
    link = root / "escape.md"
    link.symlink_to(outside)

    with pytest.raises(PathAuthorityError, match="escape root"):
        normalise_source_path(root, "../outside.md")
    with pytest.raises(PathAuthorityError, match="outside root"):
        normalise_source_path(root, outside)
    with pytest.raises(PathAuthorityError, match="symlink"):
        normalise_source_path(root, "escape.md")
