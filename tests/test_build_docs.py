from pathlib import Path
import tempfile
import unittest

from scripts import build_docs


class RetainedMarkdownStagingTests(unittest.TestCase):
    def test_stages_retained_markdown_beside_rendered_html(self) -> None:
        self.assertTrue(
            hasattr(build_docs, "stage_retained_markdown"),
            "build_docs must provide stage_retained_markdown",
        )

        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory) / "docs"
            retained = docs / "guide" / "page.html.md"
            retained.parent.mkdir(parents=True)
            retained.write_text("# Executed page\n", encoding="utf-8")
            build = docs / "build"
            (build / "guide").mkdir(parents=True)
            (build / "guide" / "page.html").write_text(
                "<html></html>", encoding="utf-8"
            )

            count = build_docs.stage_retained_markdown(docs, build)

            self.assertEqual(count, 1)
            self.assertEqual(
                (build / "guide" / "page.html.md").read_text(encoding="utf-8"),
                "# Executed page\n",
            )

    def test_retained_snapshot_reports_byte_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory) / "docs"
            page = docs / "guide" / "page.html.md"
            page.parent.mkdir(parents=True)
            page.write_bytes(b"before")

            before = build_docs.snapshot_retained_markdown(docs)
            page.write_bytes(b"after")

            self.assertEqual(
                build_docs.changed_retained_markdown(before, docs),
                [Path("guide/page.html.md")],
            )

    def test_retained_snapshot_ignores_build_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory) / "docs"
            (docs / "build").mkdir(parents=True)
            (docs / "build" / "page.html.md").write_bytes(b"disposable")

            self.assertEqual(build_docs.snapshot_retained_markdown(docs), {})

    def test_retained_snapshot_keeps_paths_containing_build(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory) / "docs"
            page = docs / "guide" / "building.html.md"
            page.parent.mkdir(parents=True)
            page.write_bytes(b"retained")

            self.assertEqual(
                list(build_docs.snapshot_retained_markdown(docs)),
                [Path("guide/building.html.md")],
            )


class DocumentationInvariantTests(unittest.TestCase):
    ROOT = Path(__file__).parents[1]

    def test_all_python_code_cells_have_unique_labels(self) -> None:
        labels = build_docs.python_code_cell_labels(self.ROOT / "docs")
        self.assertTrue(labels)
        self.assertTrue(all(labels))
        self.assertEqual(len(labels), len(set(labels)))

    def test_unlabeled_python_code_cell_is_counted_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory) / "docs"
            docs.mkdir(parents=True)
            (docs / "page.py").write_text(
                "# %%\nprint('missing label')\n", encoding="utf-8"
            )

            self.assertEqual(build_docs.python_code_cell_labels(docs), [None])

    def test_quarto_fails_on_executable_errors(self) -> None:
        config = (self.ROOT / "docs" / "_quarto.yml").read_text(encoding="utf-8")
        self.assertIn("error: false", config)

    def test_docs_ignore_html_but_not_retained_markdown(self) -> None:
        ignore = (self.ROOT / "docs" / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("**/*.html", ignore)
        self.assertNotIn("**/*.html.md", ignore)


if __name__ == "__main__":
    unittest.main()
