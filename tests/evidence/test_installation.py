from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tomllib
from pathlib import Path


SRC = Path(__file__).resolve().parents[2] / "src"


def test_tracecite_package_imports_without_knowledge_base_alias():
    import tracecite

    assert tracecite.__name__ == "tracecite"
    assert importlib.util.find_spec("knowledge_base") is None
    assert importlib.util.find_spec("tc") is None


def test_project_metadata_exposes_only_tracecite_console_script():
    pyproject = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["scripts"] == {"tracecite": "tracecite.cli:main"}


def test_console_script_is_tracecite_only():
    tracecite_exe = Path(sys.executable).with_name("tracecite")
    tcite_exe = Path(sys.executable).with_name("tcite")
    assert tracecite_exe.is_file()
    assert not tcite_exe.exists()
    result = subprocess.run(
        [str(tracecite_exe), "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "usage: tracecite" in result.stdout
