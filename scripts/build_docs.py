"""Build the Quarto documentation and generated embedding-inspection sites."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess

from tracecite.tables import export_embedding_site


def stage_retained_markdown(docs: Path, build: Path) -> int:
    """Copy Quarto's retained Markdown into the rendered site tree."""

    docs = docs.resolve()
    build = build.resolve()
    count = 0
    for source in sorted(docs.rglob("*.html.md")):
        resolved = source.resolve()
        if resolved.is_relative_to(build) or ".quarto" in source.parts:
            continue
        destination = build / resolved.relative_to(docs)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved, destination)
        count += 1
    return count


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
    docs = root / "docs"
    build = docs / "build"
    retained_count = stage_retained_markdown(docs, build)
    print(f"Documentation site: {build}")
    print(f"Retained Markdown pages: {retained_count}")

    if args.no_embedding_site:
        return 0

    result = export_embedding_site(
        build,
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
