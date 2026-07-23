#!/usr/bin/env python3
"""Validate the writing-evidence-backed-reports synthetic fixture package.

The validator deliberately shells out to the installed TraceCite CLI instead
of importing verifier internals. It creates a fresh temporary corpus and
database, generates redistributable PDFs with PyMuPDF, and checks the report
fixtures against the exact CLI contract documented by the repository.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz


FIXTURE_DIR = Path(__file__).resolve().parent
SKILL_DIR = FIXTURE_DIR.parent
CLI = shutil.which("tracecite")


def require_fixture(relative: str) -> Path:
    path = FIXTURE_DIR / relative
    if not path.exists():
        raise AssertionError(f"required fixture is missing: {path}")
    return path


def run_cli(*args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [CLI or "tracecite", *args],
        capture_output=True,
        text=True,
        timeout=180,
        env=os.environ.copy(),
    )
    if ok and result.returncode != 0:
        raise AssertionError(
            f"CLI command failed unexpectedly: {' '.join(args)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    if not ok and result.returncode == 0:
        raise AssertionError(
            f"CLI command succeeded unexpectedly: {' '.join(args)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def write_pdf(path: Path, pages: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    try:
        for paragraphs in pages:
            page = document.new_page()
            y = 72
            for paragraph in paragraphs:
                page.insert_text((72, y), paragraph, fontsize=11)
                y += 28
        document.save(path)
    finally:
        document.close()


def prepare_runtime(tmp: Path) -> tuple[Path, Path, Path, Path]:
    sources = tmp / "sources"
    reports = tmp / "reports"
    database = tmp / "runtime" / "tracecite.sqlite"
    manifest = tmp / "manifest.toml"
    source_links = tmp / "source-links.toml"

    write_pdf(
        sources / "evidence" / "planning-note.pdf",
        [
            [
                "Synthetic Planning Note",
                "The trial reserve margin remains above ten per cent in the winter peak case.",
                "Normalised quotation text spans",
                "two extracted PDF text blocks for validation.",
                "A similar sentence mentions a reserve margin, but it is deliberately not the same claim.",
            ],
            [
                "The diagram labels the reserve margin as a planning illustration rather than a forecast.",
            ],
        ],
    )
    write_pdf(
        sources / "evidence" / "counter-note.pdf",
        [
            [
                "Synthetic Counter Note",
                "A later sensitivity says the reserve margin may fall below eight per cent if outages coincide.",
            ]
        ],
    )

    manifest.write_text(
        "schema_version = 1\n"
        "[[source]]\npath = \"evidence/planning-note.pdf\"\n"
        "[[source]]\npath = \"evidence/counter-note.pdf\"\n",
        encoding="utf-8",
    )
    source_links.write_text(require_fixture("source-links.toml").read_text(encoding="utf-8"), encoding="utf-8")

    reports.mkdir(parents=True)
    for name in [
        "valid-report.md",
        "invalid-missing-definition.md",
        "invalid-unindexed-path.md",
        "invalid-bad-path.md",
        "invalid-page-not-indexed.md",
        "valid-grammar.md",
        "invalid-grammar.md",
    ]:
        shutil.copy2(require_fixture(f"reports/{name}"), reports / name)

    return sources, manifest, database, reports, source_links, tmp / "model-cache"


def assert_json_status(result: subprocess.CompletedProcess[str], expected: str) -> None:
    payload = json.loads(result.stdout)
    actual = payload.get("status")
    if actual != expected:
        raise AssertionError(f"expected status {expected!r}, got {actual!r}: {result.stdout}")


def assert_issue_kind(result: subprocess.CompletedProcess[str], expected: str) -> None:
    payload = json.loads(result.stdout)
    kinds = {issue["kind"] for issue in payload["citation_issues"]}
    if kinds != {expected}:
        raise AssertionError(f"expected only {expected!r}, got {sorted(kinds)!r}: {result.stdout}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="web-report-fixtures-") as tmp_name:
        tmp = Path(tmp_name)
        sources, manifest, database, reports, source_links, model_cache = prepare_runtime(tmp)
        common = ["--root", str(sources), "--manifest", str(manifest), "--database", str(database), "--model-cache-dir", str(model_cache)]

        run_cli("sync", *common)

        exact = run_cli(
            "verify",
            "quote",
            "evidence/planning-note.pdf",
            "1",
            "The trial reserve margin remains above ten per cent in the winter peak case.",
            "--database",
            str(database),
        )
        assert_json_status(exact, "exact")

        normalised = run_cli(
            "verify",
            "quote",
            "evidence/planning-note.pdf",
            "1",
            "Normalised quotation text spans two extracted PDF text blocks for validation.",
            "--database",
            str(database),
        )
        assert_json_status(normalised, "normalised")

        fuzzy = run_cli(
            "verify",
            "quote",
            "evidence/planning-note.pdf",
            "1",
            "The trial reserve margin remains comfortably above ten per cent in winter.",
            "--database",
            str(database),
            ok=False,
        )
        assert_json_status(fuzzy, "not-found")
        valid_text = (reports / "valid-report.md").read_text(encoding="utf-8")
        if "comfortably above ten per cent" in valid_text or "> \"The trial reserve margin remains comfortably" in valid_text:
            raise AssertionError("the similar unverifiable sentence must not appear as a quotation")
        for required in ["conflict", "available sources do not establish", "planning-note-p2"]:
            if required not in valid_text:
                raise AssertionError(f"valid report fixture is missing required guidance text: {required}")

        report_ok = run_cli(
            "verify",
            "report",
            str(reports / "valid-report.md"),
            "--root",
            str(sources),
            "--database",
            str(database),
            "--source-links",
            str(source_links),
            "--source-links-root",
            str(sources),
        )
        if not json.loads(report_ok.stdout)["ok"]:
            raise AssertionError(report_ok.stdout)

        grammar_ok = run_cli(
            "verify", "report", str(reports / "valid-grammar.md"),
            "--root", str(sources), "--database", str(database),
        )
        if not json.loads(grammar_ok.stdout)["ok"]:
            raise AssertionError(grammar_ok.stdout)

        for filename, kind in {
            "invalid-missing-definition.md": "missing-definition",
            "invalid-unindexed-path.md": "unindexed-path",
            "invalid-bad-path.md": "path-outside-root",
            "invalid-page-not-indexed.md": "page-not-indexed",
        }.items():
            result = run_cli(
                "verify",
                "report",
                str(reports / filename),
                "--root",
                str(sources),
                "--database",
                str(database),
                ok=False,
            )
            assert_issue_kind(result, kind)

        grammar_invalid = run_cli(
            "verify", "report", str(reports / "invalid-grammar.md"),
            "--root", str(sources), "--database", str(database), ok=False,
        )
        if json.loads(grammar_invalid.stdout)["quote_results"][0]["status"] != "structural-error":
            raise AssertionError(grammar_invalid.stdout)

        source_link_data = source_links.read_text(encoding="utf-8")
        for required in ['schema_version = 2', 'local_path = "evidence/planning-note.pdf"']:
            if required not in source_link_data:
                raise AssertionError(f"source-links fixture missing {required}")

        # Doctor detects stale/missing generated source derivatives without any verifier reimplementation.
        asset = next((database.parent / "imgs").rglob("*.png"))
        asset.unlink()
        doctor = run_cli("doctor", "--database", str(database), ok=False)
        if "references missing file" not in doctor.stdout:
            raise AssertionError(doctor.stdout)

    print("writing-evidence-backed-reports fixtures validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
