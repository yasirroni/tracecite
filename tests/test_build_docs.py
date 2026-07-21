from pathlib import Path
import re
import tempfile
import unittest

import yaml


def python_code_cell_labels(docs: Path) -> list[str | None]:
    marker = re.compile(r"^# %%($| (?!\[markdown\]).*$)")
    metadata = re.compile(r"^#\| label:\s*(\S+)")
    labels: list[str | None] = []
    for source in sorted(docs.rglob("*.py")):
        if "build" in source.parts or ".quarto" in source.parts:
            continue
        lines = source.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not marker.match(line):
                continue
            label = None
            for following in lines[index + 1 :]:
                if following.startswith("# %%"):
                    break
                match = metadata.match(following)
                if match:
                    label = match.group(1)
                    break
            labels.append(label)
    return labels


class DocumentationInvariantTests(unittest.TestCase):
    ROOT = Path(__file__).parents[1]

    def test_four_page_tutorial_structure_and_navigation(self) -> None:
        root = self.ROOT
        python_dir = root / "docs/examples/python"
        julia_dir = root / "docs/examples/julia"
        tutorials = {
            "python_intro": python_dir / "dirty_dataframe.py",
            "julia": julia_dir / "dirty_dataframe.jl",
            "inspect": python_dir / "hottest_temperature.py",
            "quarto": python_dir / "quarto_code_visibility.py",
        }
        self.assertTrue(all(path.is_file() for path in tutorials.values()))
        self.assertFalse((julia_dir / "hottest_temperature.jl").exists())
        self.assertEqual(
            {path.name for path in python_dir.glob("*.py")},
            {"dirty_dataframe.py", "hottest_temperature.py", "quarto_code_visibility.py"},
        )
        self.assertEqual(
            {path.name for path in julia_dir.glob("*.jl")},
            {"dirty_dataframe.jl"},
        )
        expected = {
            "_quarto-python.yml": [
                "examples/python/dirty_dataframe.py",
                "examples/python/hottest_temperature.py",
                "examples/python/quarto_code_visibility.py",
            ],
            "_quarto-julia.yml": [
                "examples/julia/dirty_dataframe.jl",
            ],
        }
        for filename, hrefs in expected.items():
            profile = yaml.safe_load((root / "docs" / filename).read_text())
            sections = profile["website"]["sidebar"]["contents"]
            tutorials_section = next(
                section for section in sections if section.get("section") == "Tutorials"
            )
            self.assertEqual(
                [item["href"] for item in tutorials_section["contents"]], hrefs
            )
            self.assertNotIn("Python EDA", str(profile))
            self.assertNotIn("Julia EDA", str(profile))

    def test_quarto_configs_have_complete_base_and_reduced_overlays(self) -> None:
        root = self.ROOT / "docs"
        base = yaml.safe_load((root / "_quarto.yml").read_text())
        python = yaml.safe_load((root / "_quarto-python.yml").read_text())
        julia = yaml.safe_load((root / "_quarto-julia.yml").read_text())
        self.assertNotIn("profile", base)
        base_render = set(base["project"]["render"])
        self.assertIn("examples/python/*.py", base_render)
        self.assertIn("examples/julia/*.jl", base_render)
        self.assertIn("examples/python/*.py", set(python["project"]["render"]))
        self.assertNotIn("examples/julia/*.jl", set(python["project"]["render"]))
        self.assertIn("examples/julia/*.jl", set(julia["project"]["render"]))
        self.assertNotIn("examples/python/*.py", set(julia["project"]["render"]))
        for config in (base, python, julia):
            render = set(config["project"]["render"])
            self.assertIn("!guide/*.html.md", render)
            self.assertIn("!formats/*.html.md", render)
        julia_text = str(julia["website"]["sidebar"])
        self.assertNotIn("examples/python/hottest_temperature.py", julia_text)
        self.assertNotIn("guide/repository_layout.py", julia_text)

    def test_tutorial_content_and_intro_behaviour_are_preserved(self) -> None:
        root = self.ROOT
        python_intro = (root / "docs/examples/python/dirty_dataframe.py").read_text()
        julia_intro = (root / "docs/examples/julia/dirty_dataframe.jl").read_text()
        inspect = (root / "docs/examples/python/hottest_temperature.py").read_text()
        quarto = (root / "docs/examples/python/quarto_code_visibility.py").read_text()
        for source in (python_intro, julia_intro):
            self.assertIn("dirty_table", source)
            self.assertIn("knowledge_table(", source)
            self.assertIn("table_id", source)
            self.assertIn("caption", source)
            self.assertIn("labels", source)
            self.assertIn("formats", source)
            self.assertIn("units", source)
            self.assertIn("row_identity", source)
            self.assertIn("summary", source)
            self.assertIn("include: false", source)
        self.assertIn("Julia is optional", julia_intro)
        self.assertIn("Julia 1.10", julia_intro)
        index = (root / "docs/index.md").read_text()
        self.assertIn("examples/python/hottest_temperature.py", index)
        self.assertNotIn(
            "[Normalise and inspect ranked results](examples/python/hottest_temperature.py)",
            index,
        )
        self.assertIn("does not rank", inspect)
        for term in ("debug-markdown", "embedding-markdown", "render-embedding-site"):
            self.assertIn(term, inspect)
        self.assertIn("#| label: quarto-hidden-table\n#| echo: false", quarto)
        self.assertIn("#| label: quarto-folded-table\n#| code-fold: true", quarto)
        self.assertIn('#| code-summary: "Show the table-generating code"', quarto)
        for label, table_id in (
            ("quarto-visible-table", "quarto-visible-table"),
            ("quarto-hidden-table", "quarto-hidden-table"),
            ("quarto-folded-table", "quarto-folded-table"),
        ):
            cell = quarto.split(f"#| label: {label}", 1)[1].split("# %%", 1)[0]
            self.assertIn(f'table_id="{table_id}"', cell)

    def test_intro_pages_keep_the_two_evidence_routes_and_outputs(self) -> None:
        root = self.ROOT
        for relative in (
            "docs/examples/python/dirty_dataframe.py",
            "docs/examples/julia/dirty_dataframe.jl",
        ):
            source = (root / relative).read_text()
            self.assertIn("HTML MIME", source)
            self.assertIn("Native Pandoc", source)
            self.assertIn("minimal", source)
            self.assertIn("advanced", source)
            self.assertIn("TraceCite", source)

    def test_dirty_dataframe_pages_show_minimal_and_commented_advanced_calls(
        self,
    ) -> None:
        docs = self.ROOT / "docs"
        pages = [
            (docs / "examples/python/dirty_dataframe.py").read_text(encoding="utf-8"),
            (docs / "examples/julia/dirty_dataframe.jl").read_text(encoding="utf-8"),
        ]
        for page in pages:
            self.assertIn("Required:", page)
            self.assertIn("Optional:", page)
            self.assertIn("summary", page)
            self.assertNotIn("echo: false", page)
        self.assertGreaterEqual(pages[0].count("knowledge_table("), 2)
        self.assertGreaterEqual(pages[1].count("knowledge_table("), 2)

    def test_docs_document_only_public_builder_commands(self) -> None:
        readme = (self.ROOT / "README.md").read_text(encoding="utf-8")
        for command in (
            "uv run tracecite docs build docs",
            "uv run tracecite docs build docs --only python",
            "uv run tracecite docs build docs --only julia",
        ):
            self.assertIn(command, readme)
        self.assertIn("tracecite prepare", readme)
        self.assertNotIn("--skip-julia", readme)
        self.assertNotIn("--tracecite", readme)
        self.assertNotIn("the `julia` profile is combined", readme)
        self.assertNotIn("profile `julia`", readme)
        for relative in (
            "docs/index.md",
            "docs/guide/embedding-site.md",
            "docs/guide/searchable-evidence.md",
        ):
            source = (self.ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("scripts/build_docs", source)

    def test_all_python_code_cells_have_unique_labels(self) -> None:
        labels = python_code_cell_labels(self.ROOT / "docs")
        self.assertTrue(labels)
        self.assertTrue(all(labels))
        self.assertEqual(len(labels), len(set(labels)))

    def test_unlabeled_python_code_cell_is_counted_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory) / "docs"
            docs.mkdir(parents=True)
            (docs / "page.py").write_text("# %%\nprint('missing label')\n", encoding="utf-8")
            self.assertEqual(python_code_cell_labels(docs), [None])

    def test_quarto_fails_on_executable_errors(self) -> None:
        config = (self.ROOT / "docs" / "_quarto.yml").read_text(encoding="utf-8")
        self.assertIn("error: false", config)

    def test_docs_ignore_html_but_not_retained_markdown(self) -> None:
        ignore = (self.ROOT / "docs" / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("**/*.html", ignore)
        self.assertNotIn("**/*.html.md", ignore)


if __name__ == "__main__":
    unittest.main()
