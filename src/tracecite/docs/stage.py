"""Conservative, atomic schema-v3 local/public Markdown source-link staging."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..evidence.source_links import (
    SourceLinkEntry,
    load_source_links,
    parse_staged_markdown_destination,
    parse_staged_source_destination,
)
from .contract import DocsEvidenceContract

StageTarget = Literal["local", "public"]
_DEFINITION = re.compile(
    r"^(?P<prefix>\s{0,3}\[[^\]]+\]:\s*)(?P<destination>\S+)(?P<suffix>\s*)$"
)
_INLINE = re.compile(r"(?P<prefix>\[[^\]]+\]\()(?P<destination>[^\s)]+)(?P<suffix>\))")
_FENCE = re.compile(r"^\s{0,3}(?P<marker>`{3,}|~{3,})(?P<suffix>.*)$")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_HTML_OPEN_TAG = re.compile(r"<(?P<tag>[A-Za-z][\w:-]*)\b[^>]*>")
_HTML_ELEMENT = re.compile(
    r"<(?P<tag>[A-Za-z][\w:-]*)\b[^>]*>.*?</(?P=tag)\s*>", re.DOTALL
)
_HTML_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "body",
    "caption",
    "center",
    "colgroup",
    "dd",
    "details",
    "dialog",
    "dir",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "head",
    "header",
    "hgroup",
    "hr",
    "html",
    "legend",
    "li",
    "main",
    "menu",
    "nav",
    "ol",
    "p",
    "pre",
    "script",
    "section",
    "summary",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "title",
    "tr",
    "ul",
}
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _protected_ranges(
    line: str, in_comment: bool
) -> tuple[list[tuple[int, int]], bool]:
    ranges: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(line):
        if in_comment:
            end = line.find("-->", cursor)
            if end < 0:
                ranges.append((cursor, len(line)))
                return ranges, True
            ranges.append((cursor, end + 3))
            cursor = end + 3
            in_comment = False
            continue
        start = line.find("<!--", cursor)
        if start < 0:
            break
        cursor = start
        in_comment = True
    ranges.extend(
        (match.start(), match.end()) for match in _HTML_ELEMENT.finditer(line)
    )
    for match in _HTML_TAG.finditer(line):
        if match.group(0).startswith("</"):
            continue
        if not any(start <= match.start() < end for start, end in ranges):
            ranges.append((match.start(), len(line)))
    return ranges, in_comment


@dataclass(frozen=True, slots=True)
class DocsStageResult:
    target: StageTarget
    staged_root: Path
    changed_files: tuple[Path, ...]


def _registry_entries(
    relative: str, markdown_path: Path, registry: dict[Path, list[SourceLinkEntry]]
) -> list[SourceLinkEntry]:
    return registry.get((markdown_path.parent / relative).resolve(), [])


def _routed_destination(
    destination: str,
    markdown_path: Path,
    output_markdown_path: Path,
    repo_root: Path,
    registry: dict[Path, list[SourceLinkEntry]],
    target: StageTarget,
) -> str | None:
    """Return the staged form of a source-link destination, or ``None`` to leave it unchanged.

    A PDF ``#page=N`` destination must resolve to exactly one registry entry.
    A local Markdown destination is routed only when it resolves to exactly
    one entry; any other Markdown link is ordinary navigation.
    """
    if "://" in destination or "?" in destination:
        return None
    if ".pdf" in destination.lower() or "#page=" in destination:
        parsed = parse_staged_source_destination(destination)
        if parsed is None:
            raise ValueError(f"malformed source-PDF destination: {destination}")
        relative, page = parsed
        entries = _registry_entries(relative, markdown_path, registry)
        if len(entries) != 1:
            raise ValueError(
                f"source-link destination has {len(entries)} registry entries: {relative}"
            )
        fragment = f"#page={page}"
    elif ".md" in destination.lower():
        parsed = parse_staged_markdown_destination(destination)
        if parsed is None:
            return None
        relative, anchor = parsed
        entries = _registry_entries(relative, markdown_path, registry)
        if len(entries) != 1:
            return None
        fragment = f"#{anchor}" if anchor else ""
    else:
        return None
    if target == "public":
        return f"{entries[0].public_url}{fragment}"
    source = (repo_root / entries[0].local_path).resolve()
    return f"{Path(os.path.relpath(source, output_markdown_path.parent)).as_posix()}{fragment}"


def _rewrite_markdown(
    text: str,
    markdown_path: Path,
    output_markdown_path: Path,
    repo_root: Path,
    registry: dict[Path, list[SourceLinkEntry]],
    target: StageTarget,
) -> str:
    output: list[str] = []
    fenced = False
    marker = ""
    frontmatter = False
    first_logical_line_seen = False
    html_comment = False
    html_block_tag: str | None = None
    table_mode = False
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        bare = line.rstrip("\r\n")
        if not first_logical_line_seen and bare.strip() == "":
            output.append(line)
            continue
        if not first_logical_line_seen and bare.strip() == "---":
            frontmatter = True
            first_logical_line_seen = True
            output.append(line)
            continue
        first_logical_line_seen = True
        if frontmatter:
            output.append(line)
            if bare.strip() == "---":
                frontmatter = False
            continue
        if html_block_tag is not None:
            output.append(line)
            if re.search(rf"</{re.escape(html_block_tag)}\s*>", bare, re.IGNORECASE):
                html_block_tag = None
            continue
        fence = _FENCE.match(bare)
        if fenced:
            output.append(line)
            if (
                fence
                and fence.group("marker")[0] == marker
                and not fence.group("suffix").strip()
            ):
                fenced = False
            continue
        if fence:
            fenced = True
            marker = fence.group("marker")[0]
            output.append(line)
            continue
        next_bare = lines[index + 1].rstrip("\r\n") if index + 1 < len(lines) else ""
        separator = bool(_TABLE_SEPARATOR.match(bare))
        table_line = (
            bare.lstrip().startswith("|")
            or separator
            or (table_mode and "|" in bare)
            or ("|" in bare and bool(_TABLE_SEPARATOR.match(next_bare)))
        )
        if table_line:
            table_mode = (
                separator
                or (table_mode and "|" in bare)
                or bare.lstrip().startswith("|")
            )
            output.append(line)
            continue
        if not bare.strip():
            table_mode = False
        if bare.startswith(("    ", "\t")):
            output.append(line)
            continue
        protected, html_comment = _protected_ranges(bare, html_comment)
        for opening in _HTML_OPEN_TAG.finditer(bare):
            tag = opening.group("tag").lower()
            if tag in _HTML_BLOCK_TAGS and not re.search(
                rf"</{re.escape(tag)}\s*>", bare[opening.end() :], re.IGNORECASE
            ):
                html_block_tag = tag
                break
        definition = _DEFINITION.match(bare)
        if definition and not any(
            start < definition.end() and definition.start() < end
            for start, end in protected
        ):
            replacement = _routed_destination(
                definition.group("destination"),
                markdown_path,
                output_markdown_path,
                repo_root,
                registry,
                target,
            )
            if replacement is not None:
                line = (
                    f"{definition.group('prefix')}{replacement}{definition.group('suffix')}"
                    + line[len(bare) :]
                )
            output.append(line)
            continue
        cursor = 0
        pieces: list[str] = []
        for match in _INLINE.finditer(bare):
            if bare[: match.start()].count("`") % 2 == 1:
                continue
            if any(
                start < match.end() and match.start() < end for start, end in protected
            ):
                continue
            if match.start() > 0 and bare[match.start() - 1] == "!":
                continue
            destination = match.group("destination")
            if destination.startswith("<"):
                continue
            replacement = _routed_destination(
                destination,
                markdown_path,
                output_markdown_path,
                repo_root,
                registry,
                target,
            )
            if replacement is not None:
                pieces.extend(
                    (
                        bare[cursor : match.start()],
                        match.group("prefix"),
                        replacement,
                        match.group("suffix"),
                    )
                )
                cursor = match.end()
        if pieces:
            pieces.append(bare[cursor:])
            line = "".join(pieces) + line[len(bare) :]
        output.append(line)
    return "".join(output)


def stage_docs(
    contract: DocsEvidenceContract,
    *,
    target: StageTarget,
    repo_root: str | Path,
    link_markdown_root: Path | None = None,
) -> DocsStageResult:
    if target not in {"local", "public"}:
        raise ValueError("target must be local or public")
    root = Path(repo_root).resolve()
    registry, issues = load_source_links(contract.source_links, root)
    if issues:
        raise ValueError("invalid source-links registry: " + "; ".join(issues))
    contract.staged_root.parent.mkdir(parents=True, exist_ok=True)
    contract.staged_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{target}-", dir=contract.staged_root.parent)
    )
    target_path = contract.staged_root / target
    backup = target_path.with_name(f".{target}.previous")
    try:
        shutil.copytree(contract.retained_root, temporary, dirs_exist_ok=True)
        changed: list[Path] = []
        link_root = link_markdown_root or contract.retained_root
        if target == "public":
            for entries in registry.values():
                for entry in entries:
                    source = (root / entry.local_path).resolve()
                    try:
                        relative = source.relative_to(link_root.resolve())
                    except ValueError:
                        continue
                    candidate = temporary / relative
                    if candidate.is_file():
                        candidate.unlink()
        for path in temporary.rglob("*.md"):
            original = path.read_text(encoding="utf-8")
            relative = path.relative_to(temporary)
            link_path = link_root / relative
            transformed = _rewrite_markdown(
                original, link_path, target_path / relative, root, registry, target
            )
            if transformed != original:
                path.write_text(transformed, encoding="utf-8")
                changed.append(path.relative_to(temporary))
        if backup.exists():
            shutil.rmtree(backup)
        if target_path.exists():
            os.replace(target_path, backup)
        os.replace(temporary, target_path)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        if backup.exists() and not target_path.exists():
            os.replace(backup, target_path)
        raise
    return DocsStageResult(target, target_path, tuple(changed))


def is_publication_excluded(path: Path, contract: DocsEvidenceContract) -> bool:
    resolved = path.resolve()
    return any(
        resolved == target or (target.is_dir() and resolved.is_relative_to(target))
        for target in (exclude.resolve() for exclude in contract.publication_exclude)
    )


def validate_retained_source_links(
    contract: DocsEvidenceContract,
    *,
    repo_root: str | Path,
) -> tuple[str, ...]:
    """Validate source-PDF/Markdown link candidates in retained Markdown without rewriting."""
    root = Path(repo_root).resolve()
    registry, issues = load_source_links(contract.source_links, root)
    if issues:
        return tuple(f"source-links registry: {issue}" for issue in issues)
    diagnostics: list[str] = []
    for path in sorted(contract.retained_root.rglob("*.md")):
        if is_publication_excluded(path, contract):
            continue
        relative = path.relative_to(contract.retained_root).as_posix()
        try:
            _rewrite_markdown(
                path.read_text(encoding="utf-8"), path, path, root, registry, "local"
            )
        except ValueError as exc:
            diagnostics.append(f"{relative}: {exc}")
    return tuple(diagnostics)
