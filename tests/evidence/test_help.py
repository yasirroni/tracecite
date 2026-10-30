from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


FORBIDDEN = (
    "pymupdf",
    "sqlite_vec",
    "sentence_transformers",
    "tracecite.evidence.sync",
    "tracecite.evidence.schema",
    "tracecite.evidence.vector_backend",
    "tracecite.evidence.parsers",
)


def _help_modules(*args: str) -> tuple[str, set[str]]:
    code = """
import contextlib, io, json, sys
from tracecite.cli import main
main_args = sys.argv[1:]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    try:
        main(main_args)
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise
print(json.dumps({'stdout': buf.getvalue(), 'modules': sorted(sys.modules)}))
"""
    env = {**os.environ, "PYTHONPATH": str(SRC), "PYTHON_COLORS": "0"}
    result = subprocess.run(
        [sys.executable, "-c", code, *args],
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )
    payload = json.loads(result.stdout)
    return payload["stdout"], set(payload["modules"])


def test_top_level_help_lists_commands_without_loading_heavy_modules():
    stdout, modules = _help_modules("--help")
    assert "usage: tracecite" in stdout
    for command in (
        "table",
        "document",
        "prepare",
        "docs",
        "check",
        "sync",
        "search",
        "doctor",
    ):
        assert command in stdout
    assert not [name for name in modules if name.startswith(FORBIDDEN)]


def test_subcommand_help_does_not_load_heavy_modules():
    for args in [
        ("sync", "--help"),
        ("search", "--help"),
        ("page", "--help"),
        ("extract-pages", "--help"),
        ("verify", "--help"),
        ("verify", "quote", "--help"),
        ("verify", "report", "--help"),
        ("prune", "--help"),
        ("doctor", "--help"),
    ]:
        stdout, modules = _help_modules(*args)
        assert "usage: tracecite" in stdout
        assert not [name for name in modules if name.startswith(FORBIDDEN)]
