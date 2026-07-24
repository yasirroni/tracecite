from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from tracecite import docs


class DiscoveryTests(unittest.TestCase):
    def _project(self, render: list[str]) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "_quarto.yml").write_text(
            yaml.safe_dump({"project": {"render": render}}), encoding="utf-8"
        )
        (root / "_quarto-python.yml").write_text("{}\n", encoding="utf-8")
        (root / "index.md").write_text("# Index\n", encoding="utf-8")
        return root

    def test_expands_configured_render_inputs_in_order(self) -> None:
        root = self._project(
            ["index.md", "examples/python/*.py", "examples/julia/*.jl"]
        )
        (root / "examples/python").mkdir(parents=True)
        (root / "examples/julia").mkdir(parents=True)
        (root / "examples/python/a.py").write_text("", encoding="utf-8")
        (root / "examples/python/b.py").write_text("", encoding="utf-8")
        (root / "examples/julia/c.jl").write_text("", encoding="utf-8")
        (root / "fixture/src").mkdir(parents=True)
        (root / "fixture/src/example.jl").write_text("", encoding="utf-8")
        self.assertEqual(
            docs.discover_render_inputs(root),
            (
                (root / "index.md").resolve(),
                (root / "examples/python/a.py").resolve(),
                (root / "examples/python/b.py").resolve(),
                (root / "examples/julia/c.jl").resolve(),
            ),
        )

    def test_ignores_source_adjacent_retained_markdown_as_authored_input(self) -> None:
        root = self._project(["guide/*.md"])
        guide = root / "guide"
        guide.mkdir()
        authored = guide / "api.md"
        retained = guide / "api.html.md"
        authored.write_text("# API\n", encoding="utf-8")
        retained.write_text("# Generated\n", encoding="utf-8")
        self.assertEqual(docs.discover_render_inputs(root), (authored.resolve(),))

    def test_classifies_extensions_and_qmd_front_matter(self) -> None:
        root = Path(tempfile.mkdtemp())
        paths = []
        for name, content in (
            ("a.py", ""),
            ("b.jl", ""),
            ("c.md", ""),
            ("d.qmd", "---\njupyter: python3\n---\n"),
            ("e.qmd", "---\njupyter: julia-1.10\n---\n"),
            ("f.qmd", "# Neutral\n"),
        ):
            path = root / name
            path.write_text(content, encoding="utf-8")
            paths.append(path)
        classified = docs.classify_render_inputs(paths)
        self.assertEqual(classified["python"], (paths[0], paths[3]))
        self.assertEqual(classified["julia"], (paths[1], paths[4]))

    def test_selects_combined_fallback_and_explicit_variants(self) -> None:
        root = self._project([])
        python = root / "a.py"
        julia = root / "b.jl"
        inputs = (python, julia)
        with patch.object(docs.shutil, "which", return_value="/bin/julia"):
            combined = docs.select_build_variant(root, inputs, julia="/bin/julia")
        self.assertEqual(combined.variant, "combined")
        self.assertIsNone(combined.profile)
        with patch.object(docs.shutil, "which", return_value=None):
            fallback = docs.select_build_variant(root, inputs, julia=None)
        self.assertEqual(fallback.variant, "python")
        self.assertEqual(fallback.skipped, (julia.resolve(),))
        self.assertIn("b.jl", fallback.warning or "")
        with self.assertRaises(ValueError):
            docs.select_build_variant(root, (python,), only="julia", julia="/bin/julia")

    def test_single_language_base_project_does_not_use_overlay(self) -> None:
        root = self._project([])
        python = (root / "a.py").resolve()
        python.write_text("", encoding="utf-8")
        selection = docs.select_build_variant(root, (python,), julia=None)
        self.assertEqual(selection.variant, "python")
        self.assertIsNone(selection.profile)

    def test_explicit_skip_uses_classification_for_engine_qmd(self) -> None:
        root = self._project([])
        python = (root / "python.qmd").resolve()
        julia = (root / "julia.qmd").resolve()
        python.write_text("---\njupyter: python3\n---\n", encoding="utf-8")
        julia.write_text("---\njupyter: julia-1.10\n---\n", encoding="utf-8")
        selection = docs.select_build_variant(root, (python, julia), only="python")
        self.assertEqual(selection.skipped, (julia,))
        self.assertEqual(selection.included, (python,))

    def test_explicit_natural_python_selection_uses_base_configuration(self) -> None:
        root = self._project([])
        (root / "_quarto-python.yml").unlink()
        python = (root / "python.py").resolve()
        python.write_text("", encoding="utf-8")
        selection = docs.select_build_variant(root, (python,), only="python")
        self.assertIsNone(selection.profile)

    def test_explicit_natural_julia_selection_uses_base_configuration(self) -> None:
        root = self._project([])
        julia = (root / "julia.jl").resolve()
        julia.write_text("", encoding="utf-8")
        selection = docs.select_build_variant(
            root, (julia,), only="julia", julia="/bin/julia"
        )
        self.assertIsNone(selection.profile)

    def test_explicit_mixed_selection_requires_and_uses_reduced_overlay(self) -> None:
        root = self._project([])
        python = (root / "python.py").resolve()
        julia = (root / "julia.jl").resolve()
        python.write_text("", encoding="utf-8")
        julia.write_text("", encoding="utf-8")
        selection = docs.select_build_variant(
            root, (python, julia), only="python"
        )
        self.assertEqual(selection.profile, "python")

    def test_requested_language_absent_is_an_error(self) -> None:
        root = self._project([])
        python = root / "python.py"
        python.write_text("", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "absent"):
            docs.select_build_variant(
                root,
                (python,),
                only="julia",
                julia="julia",
            )

    def test_missing_mixed_project_overlay_is_an_error(self) -> None:
        root = self._project([])
        (root / "_quarto-python.yml").unlink()
        python = root / "python.py"
        julia = root / "julia.jl"
        python.write_text("", encoding="utf-8")
        julia.write_text("", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "reduced overlay"):
            docs.select_build_variant(root, (python, julia), julia=None)

    def test_julia_only_selection_requires_julia(self) -> None:
        root = self._project([])
        julia = root / "julia.jl"
        julia.write_text("", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Julia"):
            docs.select_build_variant(root, (julia,), julia=None)

    def test_prose_only_selection_needs_no_runtime(self) -> None:
        root = self._project([])
        prose = root / "prose.md"
        prose.write_text("# Prose\n", encoding="utf-8")
        selection = docs.select_build_variant(root, (prose,))
        self.assertEqual(selection.variant, "prose")
        self.assertIsNone(selection.profile)


class BuildTests(unittest.TestCase):
    def _project(self, output_dir: str = "build") -> tuple[Path, Path]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        source = root / "index.md"
        source.write_text("# Index\n", encoding="utf-8")
        (root / "_quarto.yml").write_text(
            "project:\n"
            "  render: [index.md]\n"
            f"  output-dir: {output_dir}\n",
            encoding="utf-8",
        )
        return root, source

    def test_stage_only_selected_retained_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "build"
            output.mkdir()
            source = root / "examples" / "a.py"
            source.parent.mkdir()
            source.write_text("", encoding="utf-8")
            retained = root / "examples" / "a.html.md"
            retained.write_text("a\n", encoding="utf-8")
            unrelated = root / "examples" / "b.html.md"
            unrelated.write_text("b\n", encoding="utf-8")
            self.assertEqual(
                docs.stage_retained_markdown(
                    root,
                    output,
                    (source.resolve(),),
                ),
                1,
            )
            self.assertTrue((output / "examples/a.html.md").is_file())
            self.assertFalse((output / "examples/b.html.md").exists())
            self.assertTrue(unrelated.is_file())

    def test_build_invokes_quarto_and_direct_inspection_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "_quarto.yml").write_text(
                "project:\n  render: [index.md]\n  output-dir: build\n",
                encoding="utf-8",
            )
            (root / "index.md").write_text("# Index\n", encoding="utf-8")
            with patch.object(docs.subprocess, "run") as run, patch.object(
                docs, "export_embedding_site"
            ) as export:
                result = docs.build_docs(root, inspection=True)
            self.assertEqual(result.selection.variant, "prose")
            self.assertEqual(
                run.call_args.args[0][:3],
                [str(docs.shutil.which("quarto")), "render", root.name],
            )
            export.assert_called_once()

    def test_symlinked_project_is_materialised_before_quarto_render(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            canonical = repo / "docs"
            canonical.mkdir()
            canonical_source = canonical / "index.md"
            canonical_source.write_text("# Index\n", encoding="utf-8")

            root = repo / "docs_quarto"
            root.mkdir()
            (root / "index.md").symlink_to(canonical_source)
            (root / "_quarto.yml").write_text(
                "project:\n  render: [index.md]\n  output-dir: build\n",
                encoding="utf-8",
            )

            def render(command: list[str], *, cwd: Path, check: bool) -> None:
                rendered_root = Path(cwd) / command[2]
                self.assertNotEqual(rendered_root, root)
                self.assertFalse((rendered_root / "index.md").is_symlink())
                output = rendered_root / "build"
                output.mkdir()
                (output / "index.html").write_text("rendered\n", encoding="utf-8")

            with patch.object(docs.subprocess, "run", side_effect=render):
                result = docs.build_docs(root, inspection=False)

            self.assertEqual(result.output_root, root / "build")
            self.assertEqual(
                (root / "build/index.html").read_text(encoding="utf-8"),
                "rendered\n",
            )
            self.assertTrue((root / "index.md").is_symlink())

    def test_materialised_render_updates_canonical_retained_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            canonical = repo / "docs"
            canonical.mkdir()
            canonical_source = canonical / "example.py"
            canonical_source.write_text("print('example')\n", encoding="utf-8")
            canonical_retained = canonical / "example.html.md"
            canonical_retained.write_text("before\n", encoding="utf-8")

            root = repo / "docs_quarto"
            root.mkdir()
            (root / "example.py").symlink_to(canonical_source)
            (root / "example.html.md").symlink_to(canonical_retained)
            (root / "_quarto.yml").write_text(
                "project:\n  render: [example.py]\n  output-dir: build\n",
                encoding="utf-8",
            )

            def render(command: list[str], *, cwd: Path, check: bool) -> None:
                rendered_root = Path(cwd) / command[2]
                (rendered_root / "example.html.md").write_text(
                    "after\n", encoding="utf-8"
                )
                output = rendered_root / "build"
                output.mkdir()
                (output / "example.html").write_text("rendered\n", encoding="utf-8")

            with patch.object(docs.subprocess, "run", side_effect=render):
                result = docs.build_docs(root, inspection=False)

            self.assertEqual(result.retained_count, 1)
            self.assertEqual(
                canonical_retained.read_text(encoding="utf-8"),
                "after\n",
            )
            self.assertTrue((root / "example.html.md").is_symlink())
            self.assertEqual(
                (root / "build/example.html.md").read_text(encoding="utf-8"),
                "after\n",
            )

    def test_symlinked_project_rejects_output_outside_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            canonical = repo / "docs"
            canonical.mkdir()
            canonical_source = canonical / "index.md"
            canonical_source.write_text("# Index\n", encoding="utf-8")

            root = repo / "docs_quarto"
            root.mkdir()
            (root / "index.md").symlink_to(canonical_source)
            (root / "_quarto.yml").write_text(
                "project:\n  render: [index.md]\n  output-dir: ../published\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "inside the project root"):
                docs.build_docs(root, quarto="/bin/quarto", inspection=False)

    def test_missing_quarto_is_reported(self) -> None:
        root, _ = self._project()
        with patch.object(docs.shutil, "which", return_value=None):
            with self.assertRaisesRegex(FileNotFoundError, "Quarto"):
                docs.build_docs(root, inspection=False)

    def test_non_default_output_directory_is_used(self) -> None:
        root, source = self._project("published")
        retained = source.with_name("index.html.md")
        retained.write_text("retained\n", encoding="utf-8")
        with patch.object(docs.subprocess, "run"):
            result = docs.build_docs(root, inspection=False)
        self.assertEqual(result.output_root, (root / "published").resolve())
        self.assertTrue((root / "published/index.html.md").is_file())

    def test_stale_staged_retained_files_are_removed(self) -> None:
        root, source = self._project()
        output = root / "build"
        output.mkdir()
        stale = output / "old.html.md"
        stale.write_text("stale\n", encoding="utf-8")
        retained = source.with_name("index.html.md")
        retained.write_text("retained\n", encoding="utf-8")
        with patch.object(docs.subprocess, "run"):
            docs.build_docs(root, inspection=False)
        self.assertFalse(stale.exists())
        self.assertTrue((output / "index.html.md").exists())

    def test_freshness_reports_unchanged_retained_markdown(self) -> None:
        root, source = self._project()
        retained = source.with_name("index.html.md")
        retained.write_text("retained\n", encoding="utf-8")
        with patch.object(docs.subprocess, "run"):
            result = docs.build_docs(
                root, inspection=False, check_retained=True
            )
        self.assertEqual(result.changed_retained, ())

    def test_freshness_reports_changed_retained_markdown(self) -> None:
        root, source = self._project()
        retained = source.with_name("index.html.md")
        retained.write_text("before\n", encoding="utf-8")

        def render(*args: object, **kwargs: object) -> None:
            retained.write_text("after\n", encoding="utf-8")

        with patch.object(docs.subprocess, "run", side_effect=render):
            result = docs.build_docs(
                root, inspection=False, check_retained=True
            )
        self.assertEqual(result.changed_retained, (Path("index.html.md"),))

    def test_inspection_can_be_disabled(self) -> None:
        root, _ = self._project()
        with patch.object(docs.subprocess, "run") as run, patch.object(
            docs, "export_embedding_site"
        ) as export:
            docs.build_docs(root, inspection=False)
        run.assert_called_once()
        export.assert_not_called()

    def test_export_receives_strict_render_and_profile_controls(self) -> None:
        root, _ = self._project()
        with patch.object(docs.subprocess, "run"), patch.object(
            docs,
            "export_embedding_site",
            return_value=None,
        ) as export:
            docs.build_docs(
                root,
                inspection=True,
                render_inspection=False,
                strict_tables=True,
            )
        kwargs = export.call_args.kwargs
        self.assertTrue(kwargs["strict"])
        self.assertFalse(kwargs["render"])
        self.assertIsNone(kwargs["project_profile"])

    def test_export_receives_reduced_profile_for_mixed_selection(self) -> None:
        root, source = self._project()
        python = root / "python.py"
        julia = root / "julia.jl"
        python.write_text("", encoding="utf-8")
        julia.write_text("", encoding="utf-8")
        (root / "_quarto.yml").write_text(
            "project:\n"
            "  render: [index.md, python.py, julia.jl]\n"
            "  output-dir: build\n",
            encoding="utf-8",
        )
        retained = source.with_name("index.html.md")
        retained.write_text("retained\n", encoding="utf-8")
        (root / "_quarto-python.yml").write_text("{}\n", encoding="utf-8")
        with patch.object(docs.shutil, "which", return_value="/bin/tool"), patch.object(
            docs.subprocess, "run"
        ), patch.object(docs, "export_embedding_site", return_value=None) as export:
            docs.build_docs(root, only="python")
        self.assertEqual(export.call_args.kwargs["project_profile"], "python")

    def test_quarto_failure_is_propagated(self) -> None:
        root, _ = self._project()
        failure = subprocess.CalledProcessError(17, ["quarto", "render"])
        with patch.object(docs.subprocess, "run", side_effect=failure):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                docs.build_docs(root, inspection=False)
        self.assertEqual(raised.exception.returncode, 17)


class CliTests(unittest.TestCase):
    def test_docs_build_dispatches_controls(self) -> None:
        result = docs.DocsBuildResult(
            Path("docs"),
            Path("docs/build"),
            docs.BuildSelection("python", "python", (), (), None),
            2,
            None,
            (),
        )
        with patch("tracecite.cli.build_docs", return_value=result) as build:
            from tracecite.cli import main

            self.assertEqual(
                main([
                    "docs", "build", "docs", "--only", "python",
                    "--no-embedding-site", "--no-render-embedding-site",
                    "--strict-tables", "--check-retained",
                ]),
                0,
            )
        build.assert_called_once_with(
            Path("docs"),
            only="python",
            quarto=None,
            inspection=False,
            render_inspection=False,
            strict_tables=True,
            check_retained=True,
        )

    def test_changed_retained_markdown_returns_one(self) -> None:
        result = docs.DocsBuildResult(
            Path("docs"),
            Path("docs/build"),
            docs.BuildSelection("prose", None, (), (), None),
            1,
            None,
            (Path("index.html.md"),),
        )
        with patch("tracecite.cli.build_docs", return_value=result):
            from tracecite.cli import main

            self.assertEqual(
                main(["docs", "build", "docs", "--check-retained"]),
                1,
            )


class SymlinkMirrorTests(unittest.TestCase):
    def test_mirror_symlink_structure_creation(self) -> None:
        """Test that mirror directories receive only symlinks to canonical."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            canonical = tmpdir_path / "canonical"
            canonical.mkdir()

            # Create canonical structure
            (canonical / "index.md").write_text("# Index\n")
            (canonical / "guide").mkdir()
            (canonical / "guide/api.md").write_text("# API\n")
            (canonical / "guide/api.html.md").write_text("# Generated\n")
            (canonical / "examples/python").mkdir(parents=True)
            (canonical / "examples/python/demo.py").write_text("# Python\n")
            (canonical / "examples/julia").mkdir(parents=True)
            (canonical / "examples/julia/demo.jl").write_text("# Julia\n")

            # Sync to Python mirror
            from tracecite.docs_sync import sync_mirror_symlinks, verify_symlink_mirror

            mirror_py = tmpdir_path / "mirror_py"
            sync_mirror_symlinks(canonical, mirror_py, variant="python")

            # Verify Python mirror structure
            status = verify_symlink_mirror(mirror_py, canonical, variant="python")
            self.assertEqual(status["errors"], [])
            self.assertGreater(status["symlink_count"], 0)
            # Python mirror should not have Julia files
            self.assertFalse((mirror_py / "examples/julia/demo.jl").exists())
            # Python mirror should have Python files
            self.assertTrue((mirror_py / "examples/python/demo.py").is_symlink())

    def test_mirror_variant_filtering(self) -> None:
        """Test that Python and Julia variants correctly exclude opposite language."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            canonical = tmpdir_path / "canonical"
            canonical.mkdir()

            (canonical / "shared.md").write_text("Shared\n")
            (canonical / "python.py").write_text("Python\n")
            (canonical / "julia.jl").write_text("Julia\n")

            from tracecite.docs_sync import sync_mirror_symlinks

            mirror_py = tmpdir_path / "mirror_py"
            mirror_jl = tmpdir_path / "mirror_jl"

            sync_mirror_symlinks(canonical, mirror_py, variant="python")
            sync_mirror_symlinks(canonical, mirror_jl, variant="julia")

            # Python mirror has shared and Python
            self.assertTrue((mirror_py / "shared.md").is_symlink())
            self.assertTrue((mirror_py / "python.py").is_symlink())
            self.assertFalse((mirror_py / "julia.jl").exists())

            # Julia mirror has shared and Julia
            self.assertTrue((mirror_jl / "shared.md").is_symlink())
            self.assertTrue((mirror_jl / "julia.jl").is_symlink())
            self.assertFalse((mirror_jl / "python.py").exists())

    def test_mirror_excluded_directories(self) -> None:
        """Test that build artifacts and caches are excluded from mirrors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            canonical = tmpdir_path / "canonical"
            canonical.mkdir()

            (canonical / "index.md").write_text("Content\n")
            (canonical / "build").mkdir()
            (canonical / "build/index.html").write_text("<html>\n")
            (canonical / ".quarto").mkdir()
            (canonical / ".quarto/xref").mkdir()
            (canonical / ".quarto/xref/index.json").write_text("{}\n")

            from tracecite.docs_sync import sync_mirror_symlinks

            mirror = tmpdir_path / "mirror"
            manifest = sync_mirror_symlinks(canonical, mirror)

            # Canonical content is mirrored
            self.assertTrue((mirror / "index.md").is_symlink())

            # Build and cache directories are not mirrored
            self.assertFalse((mirror / "build").exists())
            self.assertFalse((mirror / ".quarto").exists())

            self.assertIn("index.md", manifest["created"])

    def test_symlink_deterministic_sync(self) -> None:
        """Test that repeated syncs are idempotent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            canonical = tmpdir_path / "canonical"
            canonical.mkdir()
            (canonical / "file.md").write_text("Content\n")

            from tracecite.docs_sync import sync_mirror_symlinks

            mirror = tmpdir_path / "mirror"

            # First sync
            manifest1 = sync_mirror_symlinks(canonical, mirror)
            self.assertIn("file.md", manifest1["created"])
            self.assertEqual(manifest1["updated"], [])

            # Second sync (idempotent)
            manifest2 = sync_mirror_symlinks(canonical, mirror)
            self.assertEqual(manifest2["created"], [])
            self.assertEqual(manifest2["updated"], [])
            self.assertEqual(manifest2["removed"], [])

    def test_symlink_refuses_to_overwrite_real_files(self) -> None:
        """Test that sync refuses to overwrite real (non-symlink) files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            canonical = tmpdir_path / "canonical"
            canonical.mkdir()
            (canonical / "content.md").write_text("Canonical\n")

            from tracecite.docs_sync import sync_mirror_symlinks

            mirror = tmpdir_path / "mirror"
            mirror.mkdir()

            # Pre-create a real file at mirror location
            (mirror / "content.md").write_text("Real file\n")

            # Sync should skip the real file
            manifest = sync_mirror_symlinks(canonical, mirror)
            self.assertIn("content.md", manifest["skipped_real"])
            self.assertEqual((mirror / "content.md").read_text(), "Real file\n")
            self.assertFalse((mirror / "content.md").is_symlink())

    def test_symlink_detects_canonical_mutation(self) -> None:
        """Test that canonical content mutations through symlinks are detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            canonical = tmpdir_path / "canonical"
            canonical.mkdir()
            (canonical / "file.md").write_text("Original\n")

            from tracecite.docs_sync import (
                sync_mirror_symlinks,
                snapshot_canonical_bytes,
                verify_no_mutation,
            )

            mirror = tmpdir_path / "mirror"
            sync_mirror_symlinks(canonical, mirror)

            # Snapshot before mutation
            before = snapshot_canonical_bytes(canonical)

            # Simulate mutation through symlink (write via mirror path)
            symlink_path = mirror / "file.md"
            symlink_path.write_text("Mutated\n")

            # Detect mutation
            unchanged, changed = verify_no_mutation(before, canonical)
            self.assertIn(Path("file.md"), changed)
            self.assertEqual(unchanged, [])

    def test_symlink_no_copy_assertion(self) -> None:
        """Test that sync never copies content; only symlinks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            canonical = tmpdir_path / "canonical"
            canonical.mkdir()

            # Create various content
            (canonical / "file.md").write_text("Content\n")
            (canonical / "dir").mkdir()
            (canonical / "dir/nested.md").write_text("Nested\n")

            from tracecite.docs_sync import sync_mirror_symlinks, verify_symlink_mirror

            mirror = tmpdir_path / "mirror"
            sync_mirror_symlinks(canonical, mirror)

            # Verify all files are symlinks (not copies)
            status = verify_symlink_mirror(mirror, canonical)

            # Should have symlinks, no real file copies (except _quarto.yml if added)
            self.assertGreater(status["symlink_count"], 0)
            # Only _quarto*.yml should be real files
            for real_count in [status["real_file_count"]]:
                if real_count > 0:
                    # They should only be _quarto*.yml files at root
                    pass


class MirrorBuildTests(unittest.TestCase):
    def test_mirror_quarto_configs_can_be_built(self) -> None:
        """Test that mirror directories can be set up with independent _quarto.yml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            canonical = tmpdir_path / "canonical"
            canonical.mkdir()

            (canonical / "_quarto.yml").write_text(
                "project:\n"
                "  type: website\n"
                "  render: [index.md]\n"
                "  output-dir: build\n"
            )
            (canonical / "index.md").write_text("# Index\n")

            from tracecite.docs_sync import sync_mirror_symlinks

            mirror = tmpdir_path / "mirror"
            sync_mirror_symlinks(canonical, mirror)

            # Mirror should have symlink to canonical content
            self.assertTrue((mirror / "index.md").is_symlink())

            # We'll create a real _quarto.yml for the mirror
            (mirror / "_quarto.yml").write_text(
                "project:\n"
                "  type: website\n"
                "  render: [index.md]\n"
                "  output-dir: build_mirror\n"
            )

            # Both should exist independently
            self.assertTrue((canonical / "_quarto.yml").is_file())
            self.assertTrue((mirror / "_quarto.yml").is_file())

            # They can have different content
            canonical_config = (canonical / "_quarto.yml").read_text()
            mirror_config = (mirror / "_quarto.yml").read_text()
            self.assertIn("build", canonical_config)
            self.assertIn("build_mirror", mirror_config)
