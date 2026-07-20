"""Create a complete, inspectable embedding-Markdown copy of a Quarto site."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

import yaml

from .document import augment_document_with_embedding_text
from .models import NORMALISER_VERSION, NormalisedTable, TableNormalisationError


_LINK_RE = re.compile(r"(\]\([^\s)]+?)\.(?:py|jl|qmd)(#[^)]+)?\)")
_OUTPUT_MARKER = ".tracecite-embedding-site"
_PROJECT_RESOURCE_SUFFIXES = {
    ".bib",
    ".csl",
    ".css",
    ".gif",
    ".jpeg",
    ".jpg",
    ".js",
    ".lua",
    ".png",
    ".sass",
    ".scss",
    ".svg",
    ".webp",
}


@dataclass(frozen=True, slots=True)
class SiteExportResult:
    source_root: Path
    output_root: Path
    page_count: int
    table_count: int
    rendered_site: Path | None


def export_embedding_site(
    source_root: Path,
    output_root: Path,
    *,
    project_config: Path | None = None,
    project_profile: str | None = None,
    source_project: Path | None = None,
    strict: bool = False,
    pandoc: str | Path | None = None,
    allow_pipe_fallback: bool = False,
    render: bool = False,
    quarto: str | Path | None = None,
    clean: bool = True,
) -> SiteExportResult:
    """Copy a rendered website as Markdown and append retrieval representations.

    ``source_root`` is normally Quarto's output directory containing retained
    ``*.html.md`` files. The original website is never modified.
    """

    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(
            f"Rendered site directory does not exist: {source_root}"
        )
    _validate_output_paths(source_root, output_root)
    _prepare_output_root(output_root, clean=clean)

    retained = _discover_retained_markdown(source_root)
    if not retained:
        raise TableNormalisationError(
            f"No retained Markdown was found under {source_root}. Render Quarto with keep-md first."
        )

    _copy_site_resources(source_root, output_root, retained)
    if source_project:
        _copy_project_resources(source_project.resolve(), output_root)
    all_tables: list[NormalisedTable] = []
    page_manifest: list[dict[str, Any]] = []

    for source_path in retained:
        relative = source_path.relative_to(source_root)
        destination_relative = _markdown_destination(relative)
        destination = output_root / destination_relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        document_label = destination_relative.as_posix()
        source_code = _infer_source_code(destination_relative, source_project)
        original = source_path.read_text(encoding="utf-8")
        transformed = augment_document_with_embedding_text(
            original,
            document_path=document_label,
            source_code_path=source_code,
            strict=strict,
            pandoc=pandoc,
            allow_pipe_fallback=allow_pipe_fallback,
        )
        destination.write_text(
            _rewrite_source_links(transformed.markdown), encoding="utf-8"
        )
        all_tables.extend(transformed.tables)
        page_manifest.append(
            {
                "source": relative.as_posix(),
                "destination": destination_relative.as_posix(),
                "tables": [table.table_id for table in transformed.tables],
            }
        )

    trace_dir = output_root / "_tracecite"
    trace_dir.mkdir(exist_ok=True)
    with (trace_dir / "tables.jsonl").open("w", encoding="utf-8") as handle:
        for table in all_tables:
            handle.write(
                json.dumps(table.to_dict(), ensure_ascii=False, sort_keys=True)
            )
            handle.write("\n")

    manifest = {
        "source_root": str(source_root),
        "output_root": str(output_root),
        "pages": page_manifest,
        "page_count": len(page_manifest),
        "table_count": len(all_tables),
        "strict": strict,
        "project_profile": project_profile,
        "normaliser_version": NORMALISER_VERSION,
    }
    (trace_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_quarto_config(
        output_root,
        project_config,
        project_profile=project_profile,
    )
    _write_embedding_landing_page(output_root, len(page_manifest), len(all_tables))

    rendered_site = None
    if render:
        rendered_site = render_embedding_site(output_root, quarto=quarto)

    return SiteExportResult(
        source_root=source_root,
        output_root=output_root,
        page_count=len(page_manifest),
        table_count=len(all_tables),
        rendered_site=rendered_site,
    )


def render_embedding_site(
    project_root: Path,
    *,
    quarto: str | Path | None = None,
) -> Path:
    command = str(quarto) if quarto else shutil.which("quarto")
    if not command:
        raise FileNotFoundError(
            "Quarto is required for --render-embedding-site but was not found on PATH."
        )
    completed = subprocess.run(
        [command, "render"],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Embedding-site Quarto render failed:\n"
            + (completed.stdout or "")
            + (completed.stderr or "")
        )
    return project_root / "_site"


def _discover_retained_markdown(source_root: Path) -> list[Path]:
    html_md = sorted(source_root.rglob("*.html.md"))
    mapped = {_markdown_destination(path.relative_to(source_root)) for path in html_md}
    plain = [
        path
        for path in sorted(source_root.rglob("*.md"))
        if not path.name.endswith(".html.md")
        and path.relative_to(source_root) not in mapped
        and "_tracecite" not in path.parts
    ]
    return [*html_md, *plain]


def _markdown_destination(relative: Path) -> Path:
    if relative.name.endswith(".html.md"):
        return relative.with_name(relative.name[: -len(".html.md")] + ".md")
    return relative


def _copy_site_resources(
    source_root: Path, output_root: Path, retained: list[Path]
) -> None:
    retained_set = {path.resolve() for path in retained}
    for path in source_root.rglob("*"):
        if path.is_dir():
            continue
        resolved = path.resolve()
        if resolved in retained_set:
            continue
        relative = path.relative_to(source_root)
        if any(
            part in {"site_libs", "_tracecite", ".quarto"} for part in relative.parts
        ):
            continue
        if path.suffix.lower() in {".html", ".json"}:
            continue
        destination = output_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def _copy_project_resources(source_project: Path, output_root: Path) -> None:
    if not source_project.is_dir():
        return
    extension_root = source_project / "_extensions"
    if extension_root.is_dir():
        shutil.copytree(
            extension_root,
            output_root / "_extensions",
            dirs_exist_ok=True,
        )
    for path in source_project.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _PROJECT_RESOURCE_SUFFIXES:
            continue
        relative = path.relative_to(source_project)
        if any(
            part in {"build", "_site", ".quarto", ".tracecite"}
            for part in relative.parts
        ):
            continue
        destination = output_root / relative
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def _write_quarto_config(
    output_root: Path,
    project_config: Path | None,
    *,
    project_profile: str | None = None,
) -> None:
    """Write a non-executing Quarto project that preserves site presentation.

    The generated project starts from the consuming repository's base config and
    selected profile, then changes only what is required for a safe Markdown-only
    inspection build. Build hooks and execution engines are intentionally removed.
    """

    original = _load_project_config(project_config, project_profile)
    config = deepcopy(original)

    raw_project = config.get("project")
    project = dict(raw_project) if isinstance(raw_project, dict) else {}
    project.setdefault("type", "website")
    project["output-dir"] = "_site"
    project["render"] = ["**/*.md", "!_tracecite/**"]
    project.pop("pre-render", None)
    project.pop("post-render", None)
    config["project"] = project

    raw_website = config.get("website")
    website = dict(raw_website) if isinstance(raw_website, dict) else {}
    title = str(website.get("title") or original.get("title") or "Documentation")
    website["title"] = f"{title} — TraceCite embedding view"
    website.setdefault("search", True)
    website.setdefault("page-navigation", True)
    website.setdefault("sidebar", {"style": "docked", "contents": "auto"})
    config["website"] = _rewrite_config_source_links(website)

    raw_format = config.get("format")
    if raw_format is None:
        config["format"] = {"html": {"toc": True, "code-fold": True}}
    elif isinstance(raw_format, dict):
        cleaned_format = deepcopy(raw_format)
        raw_html = cleaned_format.get("html")
        if isinstance(raw_html, dict):
            html_format = dict(raw_html)
            html_format.pop("keep-md", None)
            cleaned_format["html"] = html_format
        config["format"] = cleaned_format

    raw_execute = config.get("execute")
    execute = dict(raw_execute) if isinstance(raw_execute, dict) else {}
    execute["enabled"] = False
    config["execute"] = execute

    # The inspection tree contains already executed Markdown. Retaining an
    # execution engine or active profile can accidentally require Julia/Jupyter
    # again during the second, presentation-only render.
    config.pop("profile", None)
    config.pop("engines", None)
    config.pop("jupyter", None)

    (output_root / "_quarto.yml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _write_embedding_landing_page(
    output_root: Path, page_count: int, table_count: int
) -> None:
    index = output_root / "index.md"
    if index.exists():
        existing = index.read_text(encoding="utf-8")
        banner = (
            "::: {.callout-warning}\n"
            "This is the generated TraceCite embedding-inspection copy. Raw tables are preserved, "
            "and each table is followed by the exact normalised text intended for retrieval.\n"
            ":::\n\n"
        )
        if "generated TraceCite embedding-inspection copy" not in existing:
            index.write_text(
                _insert_after_front_matter(existing, banner), encoding="utf-8"
            )
        return

    index.write_text(
        "---\n"
        'title: "TraceCite embedding inspection"\n'
        "---\n\n"
        "This generated site preserves every raw Markdown or HTML table and appends the "
        "normalised retrieval representation.\n\n"
        f"- Pages copied: **{page_count}**\n"
        f"- Tables normalised: **{table_count}**\n",
        encoding="utf-8",
    )


def _infer_source_code(
    relative_markdown: Path, source_project: Path | None
) -> str | None:
    if source_project is None:
        return None
    stem = relative_markdown.with_suffix("")
    for suffix in (".py", ".jl", ".qmd"):
        candidate = source_project / stem.with_suffix(suffix)
        if candidate.is_file():
            return candidate.relative_to(source_project).as_posix()
    return None


def _rewrite_source_links(markdown: str) -> str:
    return _LINK_RE.sub(
        lambda match: f"{match.group(1)}.md{match.group(2) or ''})", markdown
    )


def _load_project_config(
    project_config: Path | None,
    project_profile: str | None,
) -> dict[str, Any]:
    if project_config is None or not project_config.is_file():
        return {}

    base = yaml.safe_load(project_config.read_text(encoding="utf-8")) or {}
    if not isinstance(base, dict):
        base = {}

    if not project_profile:
        return base

    profile_path = project_config.with_name(
        f"{project_config.stem}-{project_profile}{project_config.suffix}"
    )
    if not profile_path.is_file():
        raise FileNotFoundError(f"Quarto profile config does not exist: {profile_path}")
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    if not isinstance(profile, dict):
        raise ValueError(f"Quarto profile config must be a mapping: {profile_path}")
    return _deep_merge(base, profile)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _rewrite_config_source_links(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\.(?:py|jl|qmd)(?=#[^\s]*$|$)", ".md", value)
    if isinstance(value, list):
        return [_rewrite_config_source_links(item) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_config_source_links(item) for key, item in value.items()}
    return value


def _validate_output_paths(source_root: Path, output_root: Path) -> None:
    if source_root == output_root:
        raise ValueError(
            "Embedding-site output must differ from the rendered source site"
        )
    if output_root.is_relative_to(source_root):
        raise ValueError(
            "Embedding-site output cannot be nested inside the rendered source site"
        )
    if source_root.is_relative_to(output_root):
        raise ValueError(
            "Embedding-site output cannot be an ancestor of the rendered source site"
        )


def _prepare_output_root(output_root: Path, *, clean: bool) -> None:
    marker = output_root / _OUTPUT_MARKER
    if output_root.exists() and clean:
        nonempty = any(output_root.iterdir()) if output_root.is_dir() else True
        if nonempty and not marker.is_file():
            raise ValueError(
                f"Refusing to delete unmarked output directory: {output_root}. "
                "Choose an empty directory or use --no-clean deliberately."
            )
        if output_root.is_dir():
            shutil.rmtree(output_root)
        else:
            raise ValueError(f"Embedding-site output is not a directory: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        "Generated by TraceCite. This directory is safe to rebuild.\n",
        encoding="utf-8",
    )


def _insert_after_front_matter(markdown: str, insertion: str) -> str:
    lines = markdown.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return insertion + markdown
    for index in range(1, len(lines)):
        if lines[index].strip() in {"---", "..."}:
            return (
                "".join(lines[: index + 1])
                + "\n"
                + insertion
                + "".join(lines[index + 1 :])
            )
    return insertion + markdown
