from pathlib import Path
import re
import tempfile
import tomllib
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

    def test_independent_quarto_projects_retain_executed_markdown(self) -> None:
        for project in ("docs_quarto_py", "docs_quarto_jl"):
            config = yaml.safe_load((self.ROOT / project / "_quarto.yml").read_text())
            self.assertEqual(config["project"]["type"], "website")
            self.assertIs(config["format"]["html"]["keep-md"], True)
            self.assertIs(config["execute"]["error"], False)

    def test_documenter_environment_uses_local_tracecite_without_warnonly(self) -> None:
        project = tomllib.loads((self.ROOT / "docs_jl" / "Project.toml").read_text())
        self.assertIn("TraceCite", project["deps"])
        self.assertEqual(project["sources"]["TraceCite"]["path"], "..")

        make = (self.ROOT / "docs_jl" / "make.jl").read_text(encoding="utf-8")
        self.assertIn("quarto_percent_to_literate", make)
        self.assertNotIn("warnonly", make)

    def test_overlay_tutorial_links_point_to_existing_pages(self) -> None:
        docs = self.ROOT / "docs"
        for filename in ("_quarto-python.yml", "_quarto-julia.yml"):
            profile = yaml.safe_load((docs / filename).read_text())
            tutorials = next(
                section
                for section in profile["website"]["sidebar"]["contents"]
                if section.get("section") == "Tutorials"
            )
            hrefs = [item["href"] for item in tutorials["contents"]]
            self.assertTrue(hrefs)
            for href in hrefs:
                self.assertTrue((docs / href).is_file(), f"{filename}: {href}")

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

    def test_all_python_code_cells_have_unique_labels(self) -> None:
        labels = python_code_cell_labels(self.ROOT / "docs")
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
