from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from scripts import build_docs


class PrepareCommandTests(unittest.TestCase):
    def test_build_prepare_command_constructs_public_cli_command(self) -> None:
        self.assertEqual(
            build_docs.build_prepare_command(
                "/opt/tracecite", "/opt/quarto", "python", render=False, strict=False
            ),
            [
                "/opt/tracecite",
                "prepare",
                "docs/build",
                "--project-config",
                "docs/_quarto.yml",
                "--project-profile",
                "python",
                "--source-project",
                "docs",
                "--keep-embedding-markdown",
                ".tracecite/embedding-site",
                "--quarto",
                "/opt/quarto",
            ],
        )

    def test_build_prepare_command_adds_optional_flags(self) -> None:
        command = build_docs.build_prepare_command(
            "tracecite", "quarto", "julia", render=True, strict=True
        )

        self.assertEqual(command[-2:], ["--render-embedding-site", "--strict-tables"])


class PrepareIntegrationTests(unittest.TestCase):
    def _run_main(self, *arguments: str) -> int:
        with patch("sys.argv", ["build_docs.py", *arguments]):
            return build_docs.main()

    def test_explicit_tracecite_override_is_used_without_path_lookup(self) -> None:
        which_calls: list[str] = []

        def which(name: str) -> None:
            which_calls.append(name)
            return None

        with patch.object(build_docs.shutil, "which", side_effect=which), patch.object(
            build_docs.subprocess, "run"
        ) as run, patch.object(build_docs, "stage_retained_markdown", return_value=0):
            self._run_main(
                "--quarto",
                "quarto",
                "--tracecite",
                "custom-tracecite",
                "--skip-julia",
            )

        self.assertNotIn("tracecite", which_calls)
        self.assertEqual(run.call_args.args[0][0], "custom-tracecite")

    def test_tracecite_is_discovered_on_path_when_enabled(self) -> None:
        def which(name: str) -> str | None:
            return {"tracecite": "/bin/tracecite"}.get(name)

        with patch.object(build_docs.shutil, "which", side_effect=which), patch.object(
            build_docs.subprocess, "run"
        ) as run, patch.object(build_docs, "stage_retained_markdown", return_value=0):
            self._run_main("--quarto", "quarto", "--skip-julia")

        self.assertEqual(run.call_args.args[0][0], "/bin/tracecite")

    def test_missing_tracecite_reports_install_path_and_bypass_guidance(self) -> None:
        with (
            patch.object(build_docs.shutil, "which", return_value=None),
            patch.object(build_docs.subprocess, "run"),
            patch.object(build_docs, "stage_retained_markdown", return_value=0),
        ):
            with self.assertRaisesRegex(
                SystemExit,
                r"(?i)tracecite.*install.*PATH.*--tracecite.*--no-embedding-site",
            ):
                self._run_main("--quarto", "quarto", "--skip-julia")

    def test_no_embedding_site_bypasses_tracecite_lookup_and_invocation(self) -> None:
        with (
            patch.object(build_docs.shutil, "which", return_value=None) as which,
            patch.object(build_docs.subprocess, "run") as run,
            patch.object(build_docs, "stage_retained_markdown", return_value=0),
        ):
            self._run_main("--quarto", "quarto", "--skip-julia", "--no-embedding-site")

        which.assert_not_called()
        self.assertEqual(run.call_count, 1)

    def test_prepare_runs_after_quarto_and_staging_and_forwards_flags(self) -> None:
        events: list[str] = []

        def run(*args: object, **kwargs: object) -> None:
            events.append("subprocess")

        def stage(*args: object, **kwargs: object) -> int:
            events.append("stage")
            return 3

        with (
            patch.object(build_docs.subprocess, "run", side_effect=run) as mocked_run,
            patch.object(build_docs, "stage_retained_markdown", side_effect=stage),
        ):
            self._run_main(
                "--quarto",
                "quarto",
                "--tracecite",
                "tracecite",
                "--skip-julia",
                "--strict-tables",
                "--no-render-embedding-site",
            )

        self.assertEqual(events, ["subprocess", "stage", "subprocess"])
        self.assertEqual(mocked_run.call_args_list[1].args[0][-1], "--strict-tables")
        self.assertNotIn("--render-embedding-site", mocked_run.call_args_list[1].args[0])

    def test_prepare_failure_remains_visible(self) -> None:
        failure = subprocess.CalledProcessError(7, ["tracecite", "prepare"])
        with (
            patch.object(
                build_docs.subprocess,
                "run",
                side_effect=[None, failure],
            ),
            patch.object(build_docs, "stage_retained_markdown", return_value=0),
        ):
            with self.assertRaisesRegex(subprocess.CalledProcessError, "returned non-zero"):
                self._run_main(
                    "--quarto", "quarto", "--tracecite", "tracecite", "--skip-julia"
                )


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
                "examples/python/dirty_dataframe.py",
                "examples/julia/dirty_dataframe.jl",
                "examples/python/hottest_temperature.py",
                "examples/python/quarto_code_visibility.py",
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
        self.assertIn(
            "[Normalise and inspect ranked results](examples/python/hottest_temperature.py)",
            (root / "docs/index.md").read_text(),
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
            cell = quarto.split(f"#| label: {label}", 1)[1].split(
                "# %%", 1
            )[0]
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

    def test_readme_keeps_public_commands_and_tracecite_override(self) -> None:
        readme = (self.ROOT / "README.md").read_text(encoding="utf-8")
        code_blocks = [
            block
            for block in readme.split("```")[1::2]
            if not block.lstrip().startswith(("text", "python"))
        ]
        commands = "\n".join(code_blocks)

        self.assertRegex(commands, r"(?m)^tracecite table normalise\b")
        self.assertRegex(commands, r"(?m)^tracecite prepare\b")
        self.assertIn("--tracecite", commands)

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
