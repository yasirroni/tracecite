"""Build the Quarto documentation and generated embedding-inspection sites."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import subprocess

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


def build_prepare_command(
    tracecite: str,
    quarto: str,
    profile: str,
    *,
    render: bool,
    strict: bool,
) -> list[str]:
    """Build the public TraceCite preparation command for this repository."""
    command = [
        tracecite,
        "prepare",
        "docs/build",
        "--project-config",
        "docs/_quarto.yml",
        "--project-profile",
        profile,
        "--source-project",
        "docs",
        "--keep-embedding-markdown",
        ".tracecite/embedding-site",
        "--quarto",
        quarto,
    ]
    if render:
        command.append("--render-embedding-site")
    if strict:
        command.append("--strict-tables")
    return command


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quarto", help="Path to the Quarto executable")
    parser.add_argument("--tracecite", help="Path to the TraceCite executable")
    parser.add_argument("--skip-julia", action="store_true")
    parser.add_argument("--no-embedding-site", action="store_true")
    parser.add_argument("--no-render-embedding-site", action="store_true")
    parser.add_argument("--strict-tables", action="store_true")
    parser.add_argument("--check-retained", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    tracecite = None
    if not args.no_embedding_site:
        tracecite = args.tracecite or shutil.which("tracecite")
        if not tracecite:
            raise SystemExit(
                "tracecite CLI is required for the embedding site. Install "
                "TraceCite and ensure 'tracecite' is on PATH, pass --tracecite "
                "with its executable path, or use --no-embedding-site."
            )
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
        command = build_prepare_command(
            tracecite,
            quarto,
            profile,
            render=not args.no_render_embedding_site,
            strict=args.strict_tables,
        )
        subprocess.run(command, cwd=root, check=True)
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
