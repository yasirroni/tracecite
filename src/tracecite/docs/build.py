"""Reusable Quarto documentation-build orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import Literal, Mapping, Sequence

import yaml

from ..tables import SiteExportResult, export_embedding_site

Language = Literal["python", "julia"]
BuildVariant = Literal["combined", "python", "julia", "prose"]


@dataclass(frozen=True, slots=True)
class BuildSelection:
    variant: BuildVariant
    profile: str | None
    included: tuple[Path, ...]
    skipped: tuple[Path, ...]
    warning: str | None


@dataclass(frozen=True, slots=True)
class DocsBuildResult:
    project_root: Path
    output_root: Path
    selection: BuildSelection
    retained_count: int
    inspection: SiteExportResult | None
    changed_retained: tuple[Path, ...]


def _load_config(project_root: Path) -> dict:
    path = project_root / "_quarto.yml"
    if not path.is_file():
        raise ValueError(f"Quarto project configuration does not exist: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}


def discover_render_inputs(project_root: Path) -> tuple[Path, ...]:
    """Expand the base project's ordered ``project.render`` entries."""
    project_root = Path(project_root).resolve()
    config = _load_config(project_root)
    render = (config.get("project") or {}).get("render", [])
    if isinstance(render, str):
        render = [render]
    found: list[Path] = []
    for pattern in render:
        if not isinstance(pattern, str) or pattern.startswith("!"):
            continue
        matches = sorted(project_root.glob(pattern))
        for match in matches:
            if (
                match.is_file()
                and not match.name.endswith(".html.md")
                and match not in found
            ):
                found.append(match)
    return tuple(found)


def _qmd_language(path: Path) -> Language | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    metadata = yaml.safe_load(text[3:end]) or {}
    engine = str(metadata.get("jupyter", metadata.get("engine", ""))).lower()
    if "julia" in engine:
        return "julia"
    if engine in {"python", "python3", "jupyter"} or "python" in engine:
        return "python"
    return None


def classify_render_inputs(paths: Sequence[Path]) -> dict[Language, tuple[Path, ...]]:
    result: dict[Language, list[Path]] = {"python": [], "julia": []}
    for path in paths:
        suffix = path.suffix.lower()
        language = {".py": "python", ".jl": "julia"}.get(suffix)
        if suffix == ".qmd":
            language = _qmd_language(path)
        if language:
            result[language].append(path)
    return {key: tuple(value) for key, value in result.items()}


def select_build_variant(
    project_root: Path,
    inputs: Sequence[Path],
    *,
    only: Language | None = None,
    julia: str | None = None,
) -> BuildSelection:
    project_root = Path(project_root).resolve()
    inputs = tuple(Path(path).resolve() for path in inputs)
    classified = classify_render_inputs(inputs)
    available = {language for language, paths in classified.items() if paths}
    if only is not None and only not in {"python", "julia"}:
        raise ValueError(f"Unsupported language selection: {only}")
    if only and not classified[only]:
        raise ValueError(
            "Requested language is absent from configured render inputs: "
            f"{only}"
        )
    if only == "julia" and not julia:
        raise ValueError("Julia-only documentation build requires Julia on PATH")
    if only and len(available) > 1:
        overlay = project_root / f"_quarto-{only}.yml"
        if not overlay.is_file():
            raise ValueError(
                f"Explicit {only} build requires reduced overlay: {overlay}"
            )
    if only:
        skipped = tuple(
            path
            for language, paths in classified.items()
            if language != only
            for path in paths
        )
        profile = only if len(available) > 1 else None
        return BuildSelection(
            only,
            profile,
            tuple(path for path in inputs if path not in skipped),
            skipped,
            None,
        )
    if available == {"python", "julia"}:
        if julia:
            return BuildSelection("combined", None, tuple(inputs), (), None)
        overlay = project_root / "_quarto-python.yml"
        if not overlay.is_file():
            raise ValueError(
                "Automatic Python fallback requires reduced overlay: "
                f"{overlay}"
            )
        skipped = classified["julia"]
        warning = "Julia unavailable; skipping configured files:\n" + "\n".join(
            f"- {path.relative_to(project_root)}"
            for path in skipped
        )
        included = tuple(path for path in inputs if path not in skipped)
        return BuildSelection("python", "python", included, skipped, warning)
    if available == {"julia"}:
        if julia:
            return BuildSelection("julia", None, tuple(inputs), (), None)
        return _missing_julia()
    if available == {"python"}:
        return BuildSelection("python", None, tuple(inputs), (), None)
    return BuildSelection("prose", None, tuple(inputs), (), None)


def _missing_julia() -> BuildSelection:
    raise ValueError("Configured Julia documentation inputs require Julia on PATH")


def snapshot_retained_markdown(project_root: Path) -> dict[Path, bytes]:
    project_root = Path(project_root).resolve()
    output = _output_root(project_root)
    return {
        path.relative_to(project_root): path.read_bytes()
        for path in project_root.rglob("*.html.md")
        if not path.is_relative_to(output) and ".quarto" not in path.parts
    }


def changed_retained_markdown(
    before: Mapping[Path, bytes],
    project_root: Path,
) -> tuple[Path, ...]:
    after = snapshot_retained_markdown(project_root)
    return tuple(
        sorted(
            path
            for path in before.keys() | after.keys()
            if before.get(path) != after.get(path)
        )
    )


def stage_retained_markdown(
    project_root: Path,
    output_root: Path,
    inputs: Sequence[Path],
) -> int:
    project_root = Path(project_root).resolve()
    output_root = Path(output_root).resolve()
    for stale in output_root.rglob("*.html.md") if output_root.exists() else ():
        stale.unlink()
    count = 0
    for authored in inputs:
        retained = authored.with_name(authored.stem + ".html.md")
        if not retained.is_file():
            continue
        destination = output_root / retained.relative_to(project_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(retained, destination)
        count += 1
    return count


def _output_root(project_root: Path) -> Path:
    project = _load_config(project_root).get("project") or {}
    return project_root / project.get("output-dir", "_site")


def build_docs(
    project_root: str | Path,
    *,
    only: Language | None = None,
    quarto: str | Path | None = None,
    inspection: bool = True,
    render_inspection: bool = True,
    strict_tables: bool = False,
    check_retained: bool = False,
) -> DocsBuildResult:
    project_root = Path(project_root).resolve()
    quarto_command = str(quarto) if quarto else shutil.which("quarto")
    if not quarto_command:
        raise FileNotFoundError("Quarto is required. Install Quarto or pass --quarto.")
    inputs = discover_render_inputs(project_root)
    julia = shutil.which("julia")
    selection = select_build_variant(project_root, inputs, only=only, julia=julia)
    if selection.warning:
        print(selection.warning)
    before = snapshot_retained_markdown(project_root) if check_retained else {}
    command = [quarto_command, "render", project_root.name]
    if selection.profile:
        command.extend(["--profile", selection.profile])
    subprocess.run(command, cwd=project_root.parent, check=True)
    output_root = _output_root(project_root)
    retained_count = stage_retained_markdown(project_root, output_root, selection.included)
    exported = None
    if inspection:
        exported = export_embedding_site(
            output_root,
            project_root.parent / ".tracecite" / "embedding-site",
            project_config=project_root / "_quarto.yml",
            project_profile=selection.profile,
            source_project=project_root,
            strict=strict_tables,
            render=render_inspection,
            quarto=quarto_command,
        )
    changed = changed_retained_markdown(before, project_root) if check_retained else ()
    return DocsBuildResult(project_root, output_root, selection, retained_count, exported, changed)
