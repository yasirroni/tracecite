from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_console_script_runs():
    tracecite_exe = Path(sys.executable).with_name("tracecite")
    result = subprocess.run(
        [str(tracecite_exe), "--help"],
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHON_COLORS": "0"},
    )
    assert "usage: tracecite" in result.stdout
