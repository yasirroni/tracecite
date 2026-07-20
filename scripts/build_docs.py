"""Build the human Quarto site and the generated embedding-inspection site."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess

from tracecite.tables import export_embedding_site


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quarto", help="Path to the Quarto executable")
    parser.add_argument("--skip-julia", action="store_true")
    parser.add_argument("--no-embedding-site", action="store_true")
    parser.add_argument("--no-render-embedding-site", action="store_true")
    parser.add_argument("--strict-tables", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    quarto = args.quarto or shutil.which("quarto")
    if not quarto:
        raise SystemExit("Quarto is required. Install Quarto or pass --quarto.")

    skip_julia = args.skip_julia or shutil.which("julia") is None
    profile = "python" if skip_julia else "julia"
    command = [quarto, "render", "docs", "--profile", profile]
    if skip_julia:
        print("Julia was not found; rendering the Python-only profile.")

    subprocess.run(command, cwd=root, check=True)
    print(f"Human site: {root / 'docs' / 'build'}")

    if args.no_embedding_site:
        return 0

    result = export_embedding_site(
        root / "docs" / "build",
        root / ".tracecite" / "embedding-site",
        project_config=root / "docs" / "_quarto.yml",
        project_profile=profile,
        source_project=root / "docs",
        strict=args.strict_tables,
        render=not args.no_render_embedding_site,
        quarto=quarto,
    )
    print(f"Embedding Markdown: {result.output_root}")
    if result.rendered_site:
        print(f"Embedding inspection HTML: {result.rendered_site}")
    print(f"Pages: {result.page_count}; tables: {result.table_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
