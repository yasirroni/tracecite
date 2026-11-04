from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from tracecite.cli import build_parser

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


def _subparser(parser: argparse.ArgumentParser, *names: str) -> argparse.ArgumentParser:
    for name in names:
        subparsers = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        parser = subparsers.choices[name]
    return parser


def test_table_prepare_check_and_search_limits_describe_their_arguments():
    parser = build_parser()
    for path in (("table", "normalise"), ("prepare",), ("check",)):
        undocumented = [
            action.dest
            for action in _subparser(parser, *path)._actions
            if not isinstance(action, argparse._HelpAction) and not action.help
        ]
        assert undocumented == [], path
    for path in (("search",), ("docs", "search")):
        limits = {
            action.dest: action.help
            for action in _subparser(parser, *path)._actions
            if action.dest in {"limit", "fts_limit", "vector_limit"}
        }
        assert len(limits) == 3 and all(limits.values()), path
