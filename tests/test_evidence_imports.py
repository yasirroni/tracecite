from __future__ import annotations

import importlib
import subprocess
import sys
import unittest


class EvidenceImportTests(unittest.TestCase):
    def test_evidence_schema_imports(self) -> None:
        importlib.import_module("tracecite.evidence.schema")


    def test_top_level_help_keeps_existing_and_evidence_commands(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "tracecite", "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        help_text = result.stdout
        self.assertIn("table", help_text)
        self.assertIn("document", help_text)
        self.assertIn("prepare", help_text)
        self.assertIn("docs", help_text)
        self.assertIn("check", help_text)
        self.assertIn("sync", help_text)
        self.assertIn("search", help_text)
        self.assertIn("doctor", help_text)
        self.assertNotIn("evidence", help_text)


    def test_evidence_commands_are_top_level_without_wrapper(self) -> None:
        for command in ("sync", "search", "doctor"):
            result = subprocess.run(
                [sys.executable, "-m", "tracecite", command, "--help"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            self.assertIn(f"usage: tracecite {command}", result.stdout)


if __name__ == "__main__":
    unittest.main()
