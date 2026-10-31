import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


class RepositoryTreeTests(unittest.TestCase):
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
            (root / "docs" / "guide" / "page.md").write_text("page\n", encoding="utf-8")
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
            (root / "src" / "demo.egg-info").mkdir(parents=True)
            (root / "src" / "demo.egg-info" / "PKG-INFO").write_text(
                "generated\n", encoding="utf-8"
            )
            (root / "Manifest.toml").write_text("generated\n", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("git\n", encoding="utf-8")

            rendered = module.render_repository_tree(root, max_depth=3)

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
        self.assertNotIn("egg-info", rendered)
        self.assertNotIn("Manifest.toml", rendered)


if __name__ == "__main__":
    unittest.main()
