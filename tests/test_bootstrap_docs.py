"""Tests for the repository-only ``scripts/bootstrap_docs.py`` tool.

``scripts/`` is not part of the installed ``tracecite`` package, so these
tests exercise the script as a subprocess rather than importing it.
"""

from __future__ import annotations

from pathlib import Path
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT_SOURCE = REPO_ROOT / "scripts" / "bootstrap_docs.py"


def _run(fixture_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(fixture_root / "scripts" / "bootstrap_docs.py"), *args],
        cwd=fixture_root,
        capture_output=True,
        text=True,
    )


def _build_minimal_fixture(root: Path) -> None:
    """Build a small, self-contained tree with its own bootstrap.toml.

    Uses a fixture independent of the real repository's mapping so these
    tests do not depend on ``docs/bootstrap.toml`` staying byte-for-byte
    stable, and are fast to set up and tear down.
    """
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(BOOTSTRAP_SCRIPT_SOURCE, root / "scripts" / "bootstrap_docs.py")

    (root / "docs" / "guide").mkdir(parents=True)
    (root / "docs" / "guide" / "hello.md").write_text("# Hello\n", encoding="utf-8")

    (root / "projectA" / "guide").mkdir(parents=True)
    (root / "projectA" / "_quarto.yml").write_text("project: {}\n", encoding="utf-8")

    (root / "docs" / "bootstrap.toml").write_text(
        "schema_version = 1\n\n"
        "[[project]]\n"
        'name = "projectA"\n'
        'owned = ["_quarto.yml"]\n\n'
        "[[mapping]]\n"
        'source = "docs/guide/hello.md"\n'
        'destinations = ["projectA/guide/hello.md"]\n',
        encoding="utf-8",
    )


def _load_bootstrap_module(root: Path):
    script = root / "scripts" / "bootstrap_docs.py"
    spec = importlib.util.spec_from_file_location("fixture_bootstrap_docs", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BootstrapCleanCheckTests(unittest.TestCase):
    def test_check_is_clean_after_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_minimal_fixture(root)

            bootstrap_result = _run(root)
            self.assertEqual(bootstrap_result.returncode, 0, bootstrap_result.stderr)

            destination = root / "projectA" / "guide" / "hello.md"
            self.assertTrue(destination.is_file())
            self.assertFalse(destination.is_symlink())
            self.assertEqual(destination.read_text(encoding="utf-8"), "# Hello\n")

            manifest = root / "projectA" / ".docs-bootstrap-manifest.json"
            self.assertTrue(manifest.is_file())

            check_result = _run(root, "--check")
            self.assertEqual(check_result.returncode, 0)
            self.assertEqual(check_result.stdout, "")
            self.assertEqual(check_result.stderr, "")

    def test_check_reports_stale_destination_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_minimal_fixture(root)

            bootstrap_result = _run(root)
            self.assertEqual(bootstrap_result.returncode, 0, bootstrap_result.stderr)

            # Edit the canonical source without rerunning bootstrap: the
            # managed destination copy is now stale relative to it.
            source = root / "docs" / "guide" / "hello.md"
            source.write_text("# Hello, edited\n", encoding="utf-8")

            check_result = _run(root, "--check")
            self.assertEqual(check_result.returncode, 1)
            self.assertIn("stale", check_result.stderr)
            self.assertIn("hello.md", check_result.stderr)

    def test_check_reports_unexpected_unowned_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_minimal_fixture(root)
            self.assertEqual(_run(root).returncode, 0)

            (root / "projectA" / "leaked.md").write_text("leak\n", encoding="utf-8")
            check_result = _run(root, "--check")

            self.assertEqual(check_result.returncode, 1)
            self.assertIn("unexpected unowned file leaked.md", check_result.stderr)

    def test_failed_manifest_promotion_restores_previous_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_minimal_fixture(root)
            self.assertEqual(_run(root).returncode, 0)

            destination = root / "projectA" / "guide" / "hello.md"
            manifest = root / "projectA" / ".docs-bootstrap-manifest.json"
            old_destination = destination.read_bytes()
            old_manifest = manifest.read_bytes()
            (root / "docs" / "guide" / "hello.md").write_text(
                "# Replacement\n", encoding="utf-8"
            )

            module = _load_bootstrap_module(root)
            mappings, _ = module._load_config(root / "docs" / "bootstrap.toml")
            real_replace = module.os.replace
            calls = 0

            def fail_once_on_manifest(source, target):
                nonlocal calls
                calls += 1
                if calls == 4:
                    raise OSError("injected manifest promotion failure")
                return real_replace(source, target)

            with mock.patch.object(module.os, "replace", side_effect=fail_once_on_manifest):
                with self.assertRaisesRegex(OSError, "injected manifest"):
                    module.bootstrap(mappings)

            self.assertEqual(destination.read_bytes(), old_destination)
            self.assertEqual(manifest.read_bytes(), old_manifest)
            self.assertFalse(any(root.glob(".bootstrap-backup-*")))

    def test_bootstrap_is_idempotent_with_clean_git_status_between_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_minimal_fixture(root)

            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "add", "-A"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=Test",
                    "commit",
                    "-q",
                    "-m",
                    "seed sources",
                ],
                cwd=root,
                check=True,
            )

            first = _run(root)
            self.assertEqual(first.returncode, 0, first.stderr)

            subprocess.run(
                ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "add", "-A"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=Test",
                    "commit",
                    "-q",
                    "-m",
                    "first bootstrap",
                ],
                cwd=root,
                check=True,
            )

            second = _run(root)
            self.assertEqual(second.returncode, 0, second.stderr)

            status = subprocess.run(
                ["git", "status", "--short"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(status.stdout, "")


class BootstrapRealRepoRegressionTests(unittest.TestCase):
    """Guard the literal maintainer-reported build failure this card fixes."""

    def test_check_is_clean_against_the_real_repository(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/bootstrap_docs.py", "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_no_symlinks_remain_in_derived_source_trees(self) -> None:
        for project in ("docs_quarto_py", "docs_quarto_jl", "docs_jl"):
            project_dir = REPO_ROOT / project
            for path in project_dir.rglob("*"):
                if any(part in {"build", ".quarto", "site_libs"} for part in path.parts):
                    continue
                self.assertFalse(
                    path.is_symlink(),
                    f"unexpected symlink left in {project}: {path}",
                )

    def test_quarto_julia_only_build_no_longer_raises_already_exists(self) -> None:
        build_dir = REPO_ROOT / "docs_quarto_jl" / "build"
        if build_dir.exists():
            shutil.rmtree(build_dir)

        result = subprocess.run(
            ["uv", "run", "tracecite", "docs", "build", "docs_quarto_jl", "--only", "julia"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}",
        )
        self.assertNotIn("AlreadyExists", result.stdout + result.stderr)
        self.assertTrue((build_dir / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
