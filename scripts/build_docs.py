"""Build the Quarto documentation and generated embedding-inspection sites."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import subprocess

from tracecite.tables import export_embedding_site


def snapshot_retained_markdown(docs: Path) -> dict[Path, bytes]:
    """Return source-adjacent retained Markdown bytes, excluding output trees."""
    docs = docs.resolve()
    disposable = (docs / "build", docs / ".quarto")
    return {
        source.relative_to(docs): source.read_bytes()
        for source in sorted(docs.rglob("*.html.md"))
        if not any(source.is_relative_to(root) for root in disposable)
    }


def changed_retained_markdown(before: dict[Path, bytes], docs: Path) -> list[Path]:
    """Return retained Markdown paths whose bytes changed since *before*."""
    after = snapshot_retained_markdown(docs)
    return sorted(
        path for path in before.keys() | after.keys() if before.get(path) != after.get(path)
    )


def python_code_cell_labels(docs: Path) -> list[str | None]:
    """Extract labels from every executable percent-format Python cell."""
    marker = re.compile(r"^# %%($| (?!\[markdown\]).*$)")
    metadata = re.compile(r"^#\| label:\s*(\S+)")
    labels = []
    for source in sorted(docs.rglob("*.py")):
        if "build" in source.parts or ".quarto" in source.parts:
            continue
        lines = source.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not marker.match(line):
                continue
            label = None
            for following in lines[index + 1 :]:
                if following.startswith("# %%"):
                    break
                match = metadata.match(following)
                if match:
                    label = match.group(1)
                    break
            labels.append(label)
    return labels


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
    parser.add_argument("--check-retained", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    quarto = args.quarto or shutil.which("quarto")
    if not quarto:
        raise SystemExit("Quarto is required. Install Quarto or pass --quarto.")

    skip_julia = args.skip_julia or shutil.which("julia") is None
    profile = "python" if skip_julia else "julia"
    command = [quarto, "render", "docs", "--profile", profile]
    docs = root / "docs"
    retained_before = snapshot_retained_markdown(docs) if args.check_retained else None
    if skip_julia:
        print("Julia was not found; rendering the Python-only profile.")

    subprocess.run(command, cwd=root, check=True)
    build = docs / "build"
    retained_count = stage_retained_markdown(docs, build)
    print(f"Documentation site: {build}")
    print(f"Retained Markdown pages: {retained_count}")

    if not args.no_embedding_site:
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
    if retained_before is not None:
        changed = changed_retained_markdown(retained_before, docs)
        if changed:
            print("Retained Markdown changed:")
            print("\n".join(f"- {path}" for path in changed))
            return 1
        print("Retained Markdown is fresh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
