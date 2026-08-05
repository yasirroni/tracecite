#!/usr/bin/env python3
"""Render the authored Quarto report into TraceCite's retained Markdown root.

Run from the example's own root (this is the host-owned render hook that
``tracecite docs author`` invokes; it must not be run through TraceCite itself).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTHORED = ROOT / "docs" / "authored" / "report.qmd"
RETAINED = ROOT / "docs" / "retained" / "report.md"


def main() -> int:
    subprocess.run(
        ["quarto", "render", str(AUTHORED), "--to", "gfm", "--output", "report.md"],
        cwd=ROOT,
        check=True,
    )
    # ``--output`` is resolved relative to the invocation cwd (``ROOT``), not the
    # input file's directory, so the rendered file lands at ``ROOT/report.md``.
    rendered = ROOT / "report.md"
    RETAINED.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(rendered), str(RETAINED))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
