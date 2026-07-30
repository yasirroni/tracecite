from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


SRC = Path(__file__).resolve().parents[2] / "src"


FORBIDDEN = (
    "fitz",
    "sqlite_vec",
    "sentence_transformers",
    "tracecite.evidence.sync",
    "tracecite.evidence.schema",
    "tracecite.evidence.vector_backend",
    "tracecite.evidence.parsers",
)


def _help_modules(main_module: str, *args: str) -> tuple[str, set[str]]:
    code = """
import contextlib, importlib, io, json, sys
main = importlib.import_module(sys.argv[1]).main
main_args = sys.argv[2:]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    try:
        main(main_args)
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise
print(json.dumps({'stdout': buf.getvalue(), 'modules': sorted(sys.modules)}))
"""
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    result = subprocess.run(
        [sys.executable, "-c", code, main_module, *args],
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )
    payload = json.loads(result.stdout)
    return payload["stdout"], set(payload["modules"])


def test_top_level_help_does_not_load_heavy_modules():
    stdout, modules = _help_modules("tracecite.cli", "--help")
    assert "usage: tracecite" in stdout
    assert not [name for name in modules if name.startswith(FORBIDDEN)]


def test_subcommand_help_does_not_load_heavy_modules():
    for main_module in ["tracecite.cli", "tracecite.evidence.cli"]:
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
            stdout, modules = _help_modules(main_module, *args)
            assert "usage: tracecite" in stdout
            assert not [name for name in modules if name.startswith(FORBIDDEN)]
