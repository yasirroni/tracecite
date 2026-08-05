#!/usr/bin/env python3
"""Copy validated public staging output into the committed public/ snapshot.

Refuses to run unless ``docs check`` reports the local/public staging, the
index-input mirror, and the index database are all fresh and consistent.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    from tracecite.docs import check_docs, load_docs_contract

    config = ROOT / "docs" / "tracecite.toml"
    contract = load_docs_contract(config, repo_root=ROOT)
    result = check_docs(contract, config_path=config, repo_root=ROOT)
    if not result.ok:
        print("refusing to update public/: docs check reported issues:", file=sys.stderr)
        for issue in result.diagnostics:
            print(f"  - {issue}", file=sys.stderr)
        return 1

    staged_public = contract.staged_root / "public"
    if not staged_public.is_dir():
        print("refusing to update public/: no public staging output found", file=sys.stderr)
        return 1

    destination = ROOT / "public"
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        shutil.rmtree(temporary)
    shutil.copytree(staged_public, temporary)
    if destination.exists():
        shutil.rmtree(destination)
    temporary.rename(destination)
    print(f"updated {destination} from {staged_public}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
