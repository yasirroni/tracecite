from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd
import yaml

from tracecite.tables import (
    TableContext,
    TableNormalisationError,
    computed_first_row_summary,
    augment_document_with_embedding_text,
    export_embedding_site,
    html_table_to_markdown,
    knowledge_table,
    normalise_document_tables,
    normalise_html_table,
    normalise_pandoc_table,
)


PIPE_TABLE = """<!-- tracecite-table: {"ordering":"temperature descending","row_identity":["Place","Date"]} -->

| Rank | Place | Date | Temperature (°C) |
|---:|---|---|---:|
| 1 | Oodnadatta | 1960-01-02 | 50.7 |
| 2 | Mardie | 2022-01-13 | 50.5 |

: Highest observed temperatures. {#tbl-hot}
"""


class PandocTableTests(unittest.TestCase):
    def test_normalises_pipe_table(self) -> None:
        table = normalise_pandoc_table(
            PIPE_TABLE,
            context=TableContext(
                document_path="docs/weather.md", section_path=("Weather", "Extremes")
            ),
        )
        self.assertEqual(table.table_id, "tbl-hot")
        self.assertEqual(table.headers[-1], "Temperature (°C)")
        self.assertEqual(table.rows[0][1], "Oodnadatta")
        self.assertIn("Rank 1. Place: Oodnadatta", table.normalised_text)
        self.assertIn("Section: Weather > Extremes", table.normalised_text)
        self.assertEqual(table.diagnostics, ())

    def test_stable_fallback_id_does_not_depend_on_values(self) -> None:
        first = normalise_pandoc_table(
            """| A | B |\n|---|---|\n| x | 1 |\n""",
            context=TableContext(document_path="x.md"),
        )
        second = normalise_pandoc_table(
            """| A | B |\n|---|---|\n| y | 99 |\n""",
            context=TableContext(document_path="x.md"),
        )
        self.assertEqual(first.table_id, second.table_id)

    def test_grid_table_is_supported_by_pandoc(self) -> None:
        source = """+------+-------+\n| Rank | Value |\n+======+=======+\n| 1    | 10    |\n+------+-------+\n| 2    | 8     |\n+------+-------+\n\n: Ranked values.\n"""
        table = normalise_pandoc_table(source)
        self.assertEqual(table.headers, ("Rank", "Value"))
        self.assertEqual(len(table.rows), 2)
        self.assertIn("Rank 2", table.normalised_text)

    def test_multiline_table_preserves_multiline_cells(self) -> None:
        source = """-------------------------------------------------------------
 Centered   Default           Right Left
  Header    Aligned         Aligned Aligned
----------- ------- --------------- -------------------------
   First    row                12.0 Example of a row that
                                    spans multiple lines.

  Second    row                 5.0 Here's another one. Note
                                    the blank line between
                                    rows.
-------------------------------------------------------------

: Multiline fixture. {#tbl-multiline}
"""
        table = normalise_pandoc_table(source)
        self.assertEqual(
            table.headers,
            (
                "Centered Header",
                "Default Aligned",
                "Right Aligned",
                "Left Aligned",
            ),
        )
        self.assertEqual(
            table.rows[0][-1], "Example of a row that spans multiple lines."
        )
        self.assertIn("blank line between rows", table.rows[1][-1])

    def test_mixed_units_are_diagnosed(self) -> None:
        source = """| Rank | Temperature (°C) |\n|---:|---:|\n| 1 | 323.85 K |\n| 2 | 50.5 °C |\n\n: Mixed units. {#tbl-mixed}\n"""
        table = normalise_pandoc_table(source)
        codes = {item.code for item in table.diagnostics}
        self.assertIn("table.unit-conflict", codes)
        self.assertIn("table.mixed-units", codes)

    def test_declared_ordering_is_checked(self) -> None:
        source = """<!-- tracecite-table: {"ordering":"Value descending"} -->\n| Rank | Value |\n|---:|---:|\n| 1 | 8 |\n| 2 | 10 |\n\n: Ranked. {#tbl-ranked}\n"""
        table = normalise_pandoc_table(source)
        self.assertIn(
            "table.ordering-mismatch", {item.code for item in table.diagnostics}
        )
        with self.assertRaises(TableNormalisationError):
            normalise_pandoc_table(source, strict=True)

    def test_duplicate_rank_is_an_error(self) -> None:
        source = """| Rank | Value |\n|---:|---:|\n| 1 | 10 |\n| 1 | 8 |\n\n: Ranked. {#tbl-ranked}\n"""
        table = normalise_pandoc_table(source)
        self.assertIn("table.duplicate-rank", {item.code for item in table.diagnostics})

    def test_metadata_labels_and_units_are_applied(self) -> None:
        source = """<!-- tracecite-table: {"labels":{"tmax":"Daily maximum temperature"},"units":{"tmax":"°C"}} -->\n| place | tmax |\n|---|---:|\n| Oodnadatta | 50.7 |\n"""
        table = normalise_pandoc_table(source)
        self.assertEqual(table.headers, ("place", "Daily maximum temperature"))
        self.assertIn("Daily maximum temperature: 50.7 °C", table.normalised_text)

    def test_ragged_pipe_rows_are_preserved_and_rejected_in_strict_mode(self) -> None:
        source = (
            """| A | B |\n|---|---|\n| 1 |\n| 2 | 3 |\n\n: Ragged. {#tbl-ragged}\n"""
        )
        table = normalise_pandoc_table(source)
        self.assertEqual(table.rows, (("1", ""), ("2", "3")))
        self.assertIn("table.ragged-row", {item.code for item in table.diagnostics})
        with self.assertRaises(TableNormalisationError):
            normalise_pandoc_table(source, strict=True)

    def test_row_identity_produces_stable_ids_when_rank_changes(self) -> None:
        first = normalise_pandoc_table(
            """<!-- tracecite-table: {"row_identity":["Name"]} -->\n| Rank | Name |\n|---:|---|\n| 1 | A |\n"""
        )
        second = normalise_pandoc_table(
            """<!-- tracecite-table: {"row_identity":["Name"]} -->\n| Rank | Name |\n|---:|---|\n| 9 | A |\n""",
            context=TableContext(table_id=first.table_id),
        )
        self.assertEqual(first.row_ids, second.row_ids)

    def test_same_year_dates_are_compared_as_dates(self) -> None:
        source = """<!-- tracecite-table: {"ordering":"Date ascending"} -->\n| Date |\n|---|\n| 2024-12-01 |\n| 2024-01-01 |\n"""
        table = normalise_pandoc_table(source)
        self.assertIn(
            "table.ordering-mismatch", {item.code for item in table.diagnostics}
        )

    def test_parenthetical_note_is_not_misclassified_as_a_unit(self) -> None:
        source = """| Value (estimated) | Power (MW) |\n|---:|---:|\n| 10 | 20 |\n"""
        table = normalise_pandoc_table(source)
        self.assertEqual(table.headers, ("Value (estimated)", "Power (MW)"))
        self.assertNotIn(
            "table.header-unit-conflict", {item.code for item in table.diagnostics}
        )


class HtmlTableTests(unittest.TestCase):
    def test_html_table_normalises_through_shared_contract(self) -> None:
        source = """<table id="tbl-html"><caption>Documenter output</caption><thead><tr><th>Place</th><th>Temperature (°C)</th></tr></thead><tbody><tr><td>Oodnadatta</td><td>50.7</td></tr></tbody></table>"""
        markdown, diagnostics = html_table_to_markdown(source)
        self.assertIn("| Place | Temperature (°C) |", markdown)
        self.assertEqual(diagnostics, ())
        table = normalise_html_table(source)
        self.assertEqual(table.source_format, "html")
        self.assertEqual(table.table_id, "tbl-html")
        self.assertIn("Oodnadatta", table.normalised_text)
        self.assertEqual(table.raw_source, source)

    def test_rowspan_and_colspan_are_expanded_and_reported(self) -> None:
        source = """<table><tr><th rowspan="2">Region</th><th colspan="2">Temperature</th></tr><tr><th>Value</th><th>Unit</th></tr><tr><td>SA</td><td>50.7</td><td>°C</td></tr></table>"""
        table = normalise_html_table(source)
        self.assertEqual(len(table.headers), 3)
        self.assertIn("table.span-expanded", {item.code for item in table.diagnostics})
        self.assertIn("SA", table.normalised_text)

    def test_nested_table_is_not_flattened_silently(self) -> None:
        source = """<table><tr><th>A</th></tr><tr><td><table><tr><td>nested</td></tr></table></td></tr></table>"""
        table = normalise_html_table(source)
        self.assertFalse(table.supported)
        self.assertIn(
            "table.unsupported-nested-table", {item.code for item in table.diagnostics}
        )
        with self.assertRaises(TableNormalisationError):
            normalise_html_table(source, strict=True)


class DocumentTests(unittest.TestCase):
    def test_document_extracts_pipe_and_html_tables_but_not_code_fence(self) -> None:
        markdown = """# Report\n\n## Pandoc\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n: Native. {#tbl-native}\n\n```markdown\n| X | Y |\n|---|---|\n| 3 | 4 |\n```\n\n## Documenter\n\n<table id="tbl-doc"><tr><th>Name</th><th>Value</th></tr><tr><td>x</td><td>5</td></tr></table>\n"""
        tables = normalise_document_tables(markdown, document_path="report.md")
        self.assertEqual(
            [table.table_id for table in tables], ["tbl-native", "tbl-doc"]
        )
        self.assertEqual(tables[0].section_path, ("Report", "Pandoc"))
        self.assertEqual(tables[1].section_path, ("Report", "Documenter"))

    def test_augmentation_preserves_raw_table_and_is_idempotent(self) -> None:
        first = augment_document_with_embedding_text(
            PIPE_TABLE, document_path="weather.md"
        )
        self.assertIn("| Rank | Place | Date |", first.markdown)
        self.assertIn("TraceCite embedding representation", first.markdown)
        self.assertIn("Rank 1. Place: Oodnadatta", first.markdown)
        second = augment_document_with_embedding_text(
            first.markdown, document_path="weather.md"
        )
        self.assertEqual(first.markdown, second.markdown)

    def test_duplicate_ids_are_diagnosed(self) -> None:
        markdown = """| A |\n|---|\n| 1 |\n\n: One. {#tbl-x}\n\n| A |\n|---|\n| 2 |\n\n: Two. {#tbl-x}\n"""
        tables = normalise_document_tables(markdown)
        self.assertIn(
            "table.duplicate-id", {item.code for item in tables[1].diagnostics}
        )

    def test_documenter_raw_html_fence_is_normalised(self) -> None:
        markdown = """# Documenter\n\n```@raw html\n<table id="tbl-doc-raw"><tr><th>Name</th><th>Value</th></tr><tr><td>x</td><td>5</td></tr></table>\n```\n"""
        tables = normalise_document_tables(markdown, document_path="generated.md")
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].table_id, "tbl-doc-raw")
        self.assertEqual(tables[0].source_format, "html")
        self.assertEqual(tables[0].rows, (("x", "5"),))

    def test_metadata_labels_do_not_duplicate_ast_table(self) -> None:
        markdown = """<!-- tracecite-table: {"labels":{"tmax":"Maximum temperature"}} -->\n| place | tmax |\n|---|---:|\n| A | 50.7 |\n"""
        tables = normalise_document_tables(markdown)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].headers, ("place", "Maximum temperature"))

    def test_failed_table_is_preserved_in_non_strict_mode(self) -> None:
        markdown = """<!-- tracecite-table: {not-json} -->
| A | B |
|---|---|
| 1 | 2 |

: Broken metadata. {#tbl-broken}
"""
        tables = normalise_document_tables(markdown, document_path="broken.md")
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].table_id, "tbl-broken")
        self.assertFalse(tables[0].supported)
        self.assertEqual(tables[0].normalised_text, "")
        self.assertIn("| A | B |", tables[0].raw_source)
        self.assertIn(
            "table.normalisation-failed",
            {item.code for item in tables[0].diagnostics},
        )
        with self.assertRaises(TableNormalisationError):
            normalise_document_tables(markdown, strict=True)

    def test_failed_table_without_explicit_id_is_not_duplicated_by_ast_pass(
        self,
    ) -> None:
        markdown = """<!-- tracecite-table: {not-json} -->
| A | B |
|---|---|
| 1 | 2 |

: Broken metadata without an identifier.
"""
        tables = normalise_document_tables(markdown, document_path="broken.md")
        self.assertEqual(len(tables), 1)
        self.assertFalse(tables[0].supported)
        self.assertEqual(tables[0].caption, "Broken metadata without an identifier.")
        self.assertEqual(tables[0].metadata["raw_headers"], ["A", "B"])


class PublishTests(unittest.TestCase):
    def test_dataframe_helper_allows_captionless_table_with_required_id(self) -> None:
        frame = pd.DataFrame({"place": ["North"], "tmax": [50.7]})
        rendered = knowledge_table(frame, table_id="tbl-captionless")
        self.assertIn('"table_id": "tbl-captionless"', rendered)
        self.assertNotIn("\n: ", rendered)
        normalised = normalise_pandoc_table(
            rendered, context=TableContext(document_path="captionless.md")
        )
        self.assertEqual(normalised.table_id, "tbl-captionless")
        self.assertIsNone(normalised.caption)

    def test_dataframe_helper_keeps_captioned_pandoc_reference(self) -> None:
        frame = pd.DataFrame({"place": ["North"], "tmax": [50.7]})
        rendered = knowledge_table(
            frame, table_id="tbl-captioned", caption="Highest event."
        )
        self.assertIn(": Highest event. {#tbl-captioned}", rendered)

    def test_first_row_summary_uses_first_selected_field_as_subject(self) -> None:
        frame = pd.DataFrame(
            {
                "technology": ["Solar PV"],
                "capital_cost": [1250.0],
                "status": ["firm"],
            }
        )
        rendered = knowledge_table(
            frame,
            table_id="tbl-natural-summary",
            labels={
                "capital_cost": "Capital cost ($/kW)",
                "status": "Status",
            },
            formats={"capital_cost": ".2f"},
            units={"capital_cost": "$/kW"},
            summary=["technology", "capital_cost", "status"],
        )
        self.assertIn(
            "**First-row finding.** For **Solar PV**, capital cost ($/kW) is "
            "**1250.00 \\$/kW** and status is **firm**.", rendered
        )
        self.assertNotIn("Computed finding", rendered)

    def test_first_row_summary_handles_one_field(self) -> None:
        frame = pd.DataFrame({"status": ["firm"]})
        rendered = knowledge_table(frame, table_id="tbl-one-field", summary=["status"])
        self.assertIn("**First-row finding.** Status is **firm**.", rendered)

    def test_empty_ordered_summary_emits_empty_finding(self) -> None:
        frame = pd.DataFrame({"status": ["firm"]})
        rendered = knowledge_table(frame, table_id="tbl-empty-summary", summary=[])
        self.assertIn("**First-row finding.** No fields were selected.", rendered)

    def test_summary_title_is_source_compatible_but_not_repeated(self) -> None:
        frame = pd.DataFrame({"status": ["firm"]})
        rendered = computed_first_row_summary(
            frame, title="Legacy title", columns=["status"]
        )
        self.assertEqual(rendered, "**First-row finding.** Status is **firm**.")

    def test_first_row_summary_handles_no_fields_and_no_rows(self) -> None:
        populated = pd.DataFrame({"status": ["firm"]})
        empty = pd.DataFrame({"status": pd.Series(dtype="object")})
        self.assertEqual(
            computed_first_row_summary(populated, columns=[]),
            "**First-row finding.** No fields were selected.",
        )
        self.assertEqual(
            computed_first_row_summary(empty, columns=["status"]),
            "**First-row finding.** The table contains no rows.",
        )

    def test_dataframe_helper_is_optional_and_data_driven(self) -> None:
        frame = pd.DataFrame(
            {"rank": [1], "place": ["North | South"], "tmax": [50.7]}
        )
        rendered = knowledge_table(
            frame,
            caption="Highest event.",
            table_id="tbl-highest",
            labels={"tmax": "Temperature"},
            units={"tmax": "°C"},
            ordering="Temperature descending",
            summary=["place", "tmax"],
        )
        self.assertIn(r"North \| South", rendered)
        self.assertIn("tracecite-table", rendered)
        self.assertIn("50.7 °C", rendered)
        self.assertIn("First-row finding", rendered)


class SiteExportTests(unittest.TestCase):
    def test_export_copies_site_and_mutates_only_the_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build = root / "build"
            build.mkdir()
            raw = PIPE_TABLE
            (build / "index.html.md").write_text(raw, encoding="utf-8")
            (build / "index.html").write_text("<html></html>", encoding="utf-8")
            assets = build / "index_files"
            assets.mkdir()
            (assets / "plot.svg").write_text("<svg></svg>", encoding="utf-8")
            config = root / "_quarto.yml"
            config.write_text(
                "website:\n  title: Raw site\nformat:\n  html:\n    toc: false\n",
                encoding="utf-8",
            )
            output = root / "embedding"

            result = export_embedding_site(
                build,
                output,
                project_config=config,
                source_project=root,
            )
            self.assertEqual(result.page_count, 1)
            self.assertEqual(result.table_count, 1)
            self.assertEqual((build / "index.html.md").read_text(), raw)
            copied = (output / "index.md").read_text()
            self.assertIn("| Rank | Place | Date |", copied)
            self.assertIn("TraceCite embedding representation", copied)
            self.assertTrue((output / "index_files" / "plot.svg").is_file())
            self.assertTrue((output / "_tracecite" / "tables.jsonl").is_file())
            manifest = json.loads((output / "_tracecite" / "manifest.json").read_text())
            self.assertEqual(manifest["table_count"], 1)
            self.assertIn(
                "TraceCite embedding view", (output / "_quarto.yml").read_text()
            )

    def test_export_preserves_yaml_front_matter_before_banner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build = root / "build"
            build.mkdir()
            (build / "index.html.md").write_text(
                "---\ntitle: Demo\n---\n\n" + PIPE_TABLE,
                encoding="utf-8",
            )
            output = root / "embedding"
            export_embedding_site(build, output)
            copied = (output / "index.md").read_text(encoding="utf-8")
            self.assertTrue(copied.startswith("---\ntitle: Demo\n---\n"))
            self.assertGreater(
                copied.index("generated TraceCite"), copied.index("title: Demo")
            )

    def test_export_refuses_to_delete_unmarked_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build = root / "build"
            build.mkdir()
            (build / "index.html.md").write_text(PIPE_TABLE, encoding="utf-8")
            output = root / "embedding"
            output.mkdir()
            (output / "user-file.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(ValueError):
                export_embedding_site(build, output)

    def test_export_merges_profile_and_preserves_site_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build = root / "build"
            build.mkdir()
            (build / "index.html.md").write_text(PIPE_TABLE, encoding="utf-8")
            (root / "_quarto.yml").write_text(
                "project:\n"
                "  type: website\n"
                "  post-render: dangerous-command\n"
                "profile:\n"
                "  default: python\n"
                "website:\n"
                "  title: Raw site\n"
                "  navbar:\n"
                "    left:\n"
                "      - href: examples/python/example.py\n"
                "format:\n"
                "  html:\n"
                "    theme: cosmo\n"
                "    keep-md: true\n"
                "engines:\n"
                "  - julia\n",
                encoding="utf-8",
            )
            (root / "_quarto-python.yml").write_text(
                "website:\n"
                "  sidebar:\n"
                "    contents:\n"
                "      - href: examples/python/example.py\n",
                encoding="utf-8",
            )
            output = root / "embedding"

            export_embedding_site(
                build,
                output,
                project_config=root / "_quarto.yml",
                project_profile="python",
                source_project=root,
            )

            generated = yaml.safe_load((output / "_quarto.yml").read_text())
            self.assertEqual(generated["format"]["html"]["theme"], "cosmo")
            self.assertNotIn("keep-md", generated["format"]["html"])
            self.assertEqual(
                generated["website"]["sidebar"]["contents"][0]["href"],
                "examples/python/example.md",
            )
            self.assertEqual(
                generated["website"]["navbar"]["left"][0]["href"],
                "examples/python/example.md",
            )
            self.assertNotIn("post-render", generated["project"])
            self.assertNotIn("profile", generated)
            self.assertNotIn("engines", generated)
            self.assertFalse(generated["execute"]["enabled"])

    def test_static_markdown_is_not_reported_as_executable_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build = root / "build"
            page = build / "guide" / "page.html.md"
            page.parent.mkdir(parents=True)
            page.write_text(PIPE_TABLE, encoding="utf-8")
            source = root / "docs" / "guide"
            source.mkdir(parents=True)
            (source / "page.md").write_text("# Static page\n", encoding="utf-8")
            output = root / "embedding"

            export_embedding_site(build, output, source_project=root / "docs")

            copied = (output / "guide" / "page.md").read_text(encoding="utf-8")
            self.assertNotIn("Executable source:", copied)


class RepositoryTests(unittest.TestCase):
    def test_repository_uses_no_qmd_files_outside_examples(self) -> None:
        project = Path(__file__).resolve().parents[1]
        qmd_files = [
            path
            for path in project.rglob("*.qmd")
            if "examples/report-adoption/" not in path.as_posix()
        ]
        self.assertEqual(qmd_files, [])

    def test_only_dirty_dataframe_pages_are_paired(self) -> None:
        project = Path(__file__).resolve().parents[1]
        python_pages = {
            path.stem
            for path in (project / "docs" / "examples" / "python").glob("*.py")
        }
        julia_pages = {
            path.stem
            for path in (project / "docs" / "examples" / "julia").glob("*.jl")
        }
        self.assertTrue(python_pages)
        self.assertEqual(python_pages & julia_pages, {"dirty_dataframe"})
        self.assertFalse(
            (project / "docs" / "examples" / "julia" / "hottest_temperature.jl").exists()
        )


if __name__ == "__main__":
    unittest.main()
