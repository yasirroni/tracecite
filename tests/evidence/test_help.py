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

HELP_INVOCATIONS = [
    ["--help"],
    ["sync", "--help"],
    ["search", "--help"],
    ["page", "--help"],
    ["extract-pages", "--help"],
    ["verify", "--help"],
    ["verify", "quote", "--help"],
    ["verify", "report", "--help"],
    ["prune", "--help"],
    ["doctor", "--help"],
]


def test_help_does_not_load_heavy_modules():
    # One fresh interpreter runs every help invocation: the union of loaded
    # modules is free of heavy imports exactly when each invocation is.
    code = """
import contextlib, io, json, sys
from tracecite.cli import main
outputs = []
for args in json.loads(sys.argv[1]):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            main(args)
        except SystemExit as exc:
            if exc.code not in (0, None):
                raise
    outputs.append(buf.getvalue())
print(json.dumps({'outputs': outputs, 'modules': sorted(sys.modules)}))
"""
    env = {**os.environ, "PYTHONPATH": str(SRC), "PYTHON_COLORS": "0"}
    result = subprocess.run(
        [sys.executable, "-c", code, json.dumps(HELP_INVOCATIONS)],
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )
    payload = json.loads(result.stdout)
    assert all(out.startswith("usage: tracecite") for out in payload["outputs"])
    assert not [name for name in payload["modules"] if name.startswith(FORBIDDEN)]
