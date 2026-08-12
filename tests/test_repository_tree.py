from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import tempfile
import unittest


class RepositoryTreeTests(unittest.TestCase):
    def test_all_examples_live_under_docs(self) -> None:
        project = Path(__file__).resolve().parents[1]
        self.assertFalse((project / "examples").exists())
        report_example = (
            project
            / "docs"
            / "examples"
            / "report-adoption"
            / "aemo-isp-comparison"
        )
        self.assertTrue((report_example / "index.md").is_file())
        self.assertTrue((report_example / "docs" / "authored" / "report.qmd").is_file())
        workbook_example = project / "docs" / "examples" / "workbook-vector-search"
        self.assertTrue((workbook_example / "index.md").is_file())
        self.assertTrue(
            (
                workbook_example
                / "sources"
                / "aemo"
                / "2023-iasr-ev-workbook.xlsx"
            ).is_file()
        )
        self.assertFalse((project / "docs" / "assets" / "workbooks").exists())
        self.assertFalse((project / "docs" / "guide" / "workbook-vector-search.md").exists())

    def test_literate_documenter_fixture_uses_canonical_docs_path(self) -> None:
        project = Path(__file__).resolve().parents[1]
        canonical = project / "docs" / "examples" / "literate_documenter"
        old = project / "examples" / "literate_documenter"

        for relative in (
            "Project.toml",
            "src/temperature_eda.jl",
            "docs/make.jl",
            "docs/src/index.md",
            "index.md",
        ):
            self.assertTrue((canonical / relative).is_file(), relative)
        self.assertFalse(old.exists())

        format_page = (project / "docs" / "formats" / "html-documenter.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("docs/examples/literate_documenter/", format_page)

        for profile_name in ("_quarto-python.yml", "_quarto-julia.yml"):
            profile = (project / "docs" / profile_name).read_text(encoding="utf-8")
            self.assertIn("examples/literate_documenter/index.md", profile)

    def test_tree_has_a_hidden_source_guide_page(self) -> None:
        project = Path(__file__).resolve().parents[1]
        page = project / "docs" / "guide" / "repository_layout.py"

        self.assertTrue(page.is_file())
        source = page.read_text(encoding="utf-8")
        self.assertIn("#| echo: false", source)
        self.assertNotIn("docs/examples/repository_layout.py", source)

    def test_tree_respects_depth_and_excludes_generated_directories(self) -> None:
        project = Path(__file__).resolve().parents[1]
        script = project / "scripts" / "render_repository_tree.py"
        self.assertTrue(script.is_file())
        spec = spec_from_file_location("render_repository_tree", script)
        assert spec and spec.loader
        module = module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("demo\n", encoding="utf-8")
            (root / "docs" / "guide" / "deep").mkdir(parents=True)
            (root / "docs" / "guide" / "page.md").write_text(
                "page\n", encoding="utf-8"
            )
            (root / "docs" / "guide" / "deep" / "hidden.md").write_text(
                "hidden\n", encoding="utf-8"
            )
            (root / "docs" / "build").mkdir(parents=True)
            (root / "docs" / "build" / "index.html").write_text(
                "generated\n", encoding="utf-8"
            )
            (root / "docs" / "guide" / "page.html").write_text(
                "temporary\n", encoding="utf-8"
            )
            (root / "docs" / "guide" / "page.quarto_ipynb").write_text(
                "temporary\n", encoding="utf-8"
            )
            (root / "docs" / "old" / ".cache").mkdir(parents=True)
            (root / "src" / "demo.egg-info").mkdir(parents=True)
            (root / "src" / "demo.egg-info" / "PKG-INFO").write_text(
                "generated\n", encoding="utf-8"
            )
            (root / "Manifest.toml").write_text("generated\n", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("git\n", encoding="utf-8")
            (root / ".superpowers" / "specs").mkdir(parents=True)
            (root / ".superpowers" / "specs" / "internal.md").write_text(
                "internal\n", encoding="utf-8"
            )
            (root / "docs" / ".superpowers").mkdir(parents=True)
            (root / "docs" / ".superpowers" / "public.md").write_text(
                "public\n", encoding="utf-8"
            )
            (root / ".env.example").write_text("secret\n", encoding="utf-8")
            (root / "docs" / ".gitignore").write_text("ignored\n", encoding="utf-8")
            (root / "docs" / "guide" / ".hidden").mkdir()
            (root / "docs" / "guide" / ".hidden" / "nested.md").write_text(
                "nested\n", encoding="utf-8"
            )

            rendered = module.render_repository_tree(root, max_depth=3)

            self.assertTrue(module._is_excluded(root, root / ".superpowers"))
            self.assertTrue(module._is_excluded(root, root / "docs" / ".superpowers"))
            self.assertTrue(module._is_excluded(root, root / ".env.example"))
            self.assertTrue(module._is_excluded(root, root / "docs" / ".gitignore"))
            self.assertTrue(module._is_excluded(root, root / "docs" / "guide" / ".hidden"))
        self.assertIn("README.md", rendered)
        self.assertIn("docs/", rendered)
        self.assertIn("guide/", rendered)
        self.assertIn("page.md", rendered)
        self.assertIn("deep/", rendered)
        self.assertNotIn("hidden.md", rendered)
        self.assertNotIn("build/", rendered)
        self.assertNotIn(".git/", rendered)
        self.assertNotIn("page.html", rendered)
        self.assertNotIn("quarto_ipynb", rendered)
        self.assertNotIn("old/", rendered)
        self.assertNotIn("egg-info", rendered)
        self.assertNotIn("Manifest.toml", rendered)
        self.assertNotIn("internal.md", rendered)
        self.assertNotIn("public.md", rendered)
        self.assertNotIn(".env.example", rendered)
        self.assertNotIn(".gitignore", rendered)
        self.assertNotIn("nested.md", rendered)


if __name__ == "__main__":
    unittest.main()
