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


if __name__ == "__main__":
    unittest.main()
