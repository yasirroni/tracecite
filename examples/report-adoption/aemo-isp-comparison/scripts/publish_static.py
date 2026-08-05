#!/usr/bin/env python3
"""Publish the committed public snapshot and static assets, stdlib-only.

Runs under ``python3 -S`` with no TraceCite installation, source PDFs,
database, index-input mirror, model cache, or Quarto runtime available: only
the committed ``public/`` and ``static/`` directories are read.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: publish_static.py OUTPUT_DIR", file=sys.stderr)
        return 2
    output = Path(argv[0]).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    public = ROOT / "public"
    if public.is_dir():
        shutil.copytree(public, output / "public", dirs_exist_ok=True)
    static = ROOT / "static"
    if static.is_dir() and any(static.iterdir()):
        shutil.copytree(static, output / "static", dirs_exist_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
