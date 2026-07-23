"""Host-owned static publish fixture; intentionally stdlib-only."""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).parent
OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_generated"
OUTPUT.mkdir(parents=True, exist_ok=True)
shutil.copy2(ROOT / "index.md", OUTPUT / "index.md")
shutil.copy2(ROOT / "figure.svg", OUTPUT / "figure.svg")
print(OUTPUT)
