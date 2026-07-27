import importlib.metadata
import subprocess
import sys

import tracecite


def test_runtime_version_surfaces_match_distribution_metadata() -> None:
    expected = importlib.metadata.version("tracecite")

    assert tracecite.__version__ == expected

    result = subprocess.run(
        [sys.executable, "-m", "tracecite", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == f"TraceCite {expected}\n"
