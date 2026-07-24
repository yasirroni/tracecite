"""Reusable Quarto documentation-build orchestration."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Iterator, Literal, Mapping, Sequence

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
    inputs = tuple(
        path if path.is_absolute() else project_root / path
        for path in (Path(path) for path in inputs)
    )
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
        retained = _retained_destination(authored)
        if not retained.is_file():
            continue
        relative = authored.relative_to(project_root)
        destination = output_root / relative.with_name(
            relative.stem + ".html.md"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(retained, destination)
        count += 1
    return count


def _output_root(project_root: Path) -> Path:
    project = _load_config(project_root).get("project") or {}
    return project_root / project.get("output-dir", "_site")


def _contains_source_symlinks(project_root: Path, output_root: Path) -> bool:
    """Return whether a Quarto source tree contains symlinked inputs/resources."""
    project_root = project_root.resolve()
    output_root = output_root.resolve()
    for path in project_root.rglob("*"):
        if path.is_relative_to(output_root) or ".quarto" in path.parts:
            continue
        if path.is_symlink():
            return True
    return False


def _copy_project_without_build_outputs(
    project_root: Path,
    staged_root: Path,
    output_root: Path,
) -> None:
    """Materialise a symlinked Quarto project as ordinary files for rendering."""
    try:
        output_relative = output_root.relative_to(project_root)
    except ValueError as error:
        raise ValueError(
            "Symlinked Quarto projects require project.output-dir to remain "
            f"inside the project root: {output_root}"
        ) from error
    if not output_root.resolve().is_relative_to(project_root.resolve()):
        raise ValueError(
            "Symlinked Quarto projects require project.output-dir to remain "
            f"inside the project root: {output_root}"
        )

    def ignore(directory: str, names: list[str]) -> set[str]:
        relative = Path(directory).relative_to(project_root)
        ignored: set[str] = set()
        for name in names:
            candidate = relative / name
            if candidate == output_relative or name == ".quarto":
                ignored.add(name)
        return ignored

    shutil.copytree(
        project_root,
        staged_root,
        symlinks=False,
        ignore=ignore,
        dirs_exist_ok=True,
    )


def _retained_destination(authored: Path) -> Path:
    """Return the canonical retained-Markdown destination for an authored input."""
    canonical = authored.resolve() if authored.is_symlink() else authored
    return canonical.with_name(canonical.stem + ".html.md")


def _publish_materialised_render(
    staged_root: Path,
    project_root: Path,
    inputs: Sequence[Path],
) -> None:
    """Publish a successful staged render and its retained Markdown."""
    staged_output = _output_root(staged_root)
    output_root = _output_root(project_root)
    if not staged_output.is_dir():
        raise RuntimeError(
            f"Quarto did not create the configured output: {staged_output}"
        )

    for authored in inputs:
        relative = authored.relative_to(project_root)
        staged_authored = staged_root / relative
        staged_retained = staged_authored.with_name(
            staged_authored.stem + ".html.md"
        )
        if not staged_retained.is_file():
            continue
        destination = _retained_destination(authored)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged_retained, destination)

    if output_root.exists() or output_root.is_symlink():
        if output_root.is_symlink() or output_root.is_file():
            output_root.unlink()
        else:
            shutil.rmtree(output_root)
    shutil.copytree(staged_output, output_root, symlinks=False)


@contextmanager
def _render_project_root(
    project_root: Path,
    output_root: Path,
) -> Iterator[tuple[Path, bool]]:
    """Yield a Quarto-safe project root, materialising symlinks when required."""
    if not _contains_source_symlinks(project_root, output_root):
        yield project_root, False
        return

    staged_root = Path(
        tempfile.mkdtemp(
            prefix=f".{project_root.name}-render-",
            dir=project_root.parent,
        )
    )
    try:
        _copy_project_without_build_outputs(project_root, staged_root, output_root)
        yield staged_root, True
    finally:
        shutil.rmtree(staged_root, ignore_errors=True)


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
    output_root = _output_root(project_root)
    with _render_project_root(project_root, output_root) as (render_root, staged):
        command = [quarto_command, "render", render_root.name]
        if selection.profile:
            command.extend(["--profile", selection.profile])
        subprocess.run(command, cwd=render_root.parent, check=True)
        if staged:
            _publish_materialised_render(
                render_root,
                project_root,
                selection.included,
            )
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
