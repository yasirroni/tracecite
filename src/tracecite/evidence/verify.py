from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import posixpath
import re

from .chunking import normalise_text
from .paths import PathAuthorityError, normalise_source_path, source_row_for_path
from .source_links import (
    SourceLinkEntry,
    load_source_links,
    parse_source_link_destination,
)

_DEFINITION_RE = re.compile(
    r"^\[(?P<key>[^\]]+)\]:\s*(?:<(?P<angle>.*?)#page=(?P<angle_page>-?\d+)>|(?P<bare>.*?)#page=(?P<bare_page>-?\d+))\s*$"
)
_DEFINITION_LIKE_RE = re.compile(r"^\[(?P<key>[^\]]+)\]:")
_CITATION_RE = re.compile(r"\[[^\]]*\]\[(?P<key>[^\]]+)\]")
_BLOCKQUOTE_RE = re.compile(r"^>\s?(?P<quote>.*)$")
_FENCE_RE = re.compile(r"^\s{0,3}(?P<marker>`{3,}|~{3,})(?P<suffix>.*)$")


@dataclass(frozen=True)
class QuoteVerification:
    status: str
    physical_page: int
    quote: str
    matched_key: str | None = None
    source_path: str | None = None

    @property
    def citation_key(self) -> str | None:
        return self.matched_key


def verify_quote(conn, source_path: str, physical_page: int, quote: str) -> QuoteVerification:
    if not quote.strip():
        return QuoteVerification("structural-error", physical_page, quote, source_path=source_path)
    row = conn.execute(
        """
        SELECT pages.text FROM pages
        JOIN sources ON sources.source_pk = pages.source_pk
        WHERE sources.path = ? AND pages.physical_page = ?
        """,
        (source_path, physical_page),
    ).fetchone()
    if row is None:
        return QuoteVerification("not-found", physical_page, quote, source_path=source_path)
    page_text = row["text"]
    if quote in page_text:
        return QuoteVerification("exact", physical_page, quote, source_path=source_path)
    if normalise_text(quote) in normalise_text(page_text):
        return QuoteVerification("normalised", physical_page, quote, source_path=source_path)
    return QuoteVerification("not-found", physical_page, quote, source_path=source_path)


@dataclass
class ReferenceDefinition:
    key: str
    page: int
    path: str


@dataclass
class CitationIssue:
    key: str
    kind: str
    detail: str


@dataclass
class ReportVerification:
    definitions: dict[str, ReferenceDefinition] = field(default_factory=dict)
    citation_keys_used: set[str] = field(default_factory=set)
    citation_issues: list[CitationIssue] = field(default_factory=list)
    quote_results: list[QuoteVerification] = field(default_factory=list)
    source_link_issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.citation_issues and not self.source_link_issues and all(
            q.status in {"exact", "normalised"} for q in self.quote_results
        )


def _normalise_relative_path(path: str) -> str:
    return posixpath.normpath(path.replace("\\", "/"))


def _parse_definitions(lines: list[str]) -> tuple[dict[str, ReferenceDefinition], list[CitationIssue], set[str]]:
    out: dict[str, ReferenceDefinition] = {}
    issues: list[CitationIssue] = []
    invalid_keys: set[str] = set()
    for line in lines:
        match = _DEFINITION_RE.match(line)
        if match:
            destination = match.group("angle") or match.group("bare") or ""
            page = match.group("angle_page") or match.group("bare_page")
            parsed = parse_source_link_destination(
                f"<{destination}#page={page}>" if match.group("angle") is not None
                else f"{destination}#page={page}"
            )
            if parsed is None:
                invalid_keys.add(match.group("key"))
                continue
            destination, parsed_page = parsed
            definition = ReferenceDefinition(match.group("key"), parsed_page, destination)
            existing = out.get(definition.key)
            if existing is not None:
                kind = "duplicate-definition" if (existing.path, existing.page) == (definition.path, definition.page) else "ambiguous-definition"
                issues.append(CitationIssue(definition.key, kind, "duplicate reference definition label"))
                invalid_keys.add(definition.key)
                continue
            out[definition.key] = definition
            continue
        like = _DEFINITION_LIKE_RE.match(line)
        if like:
            key = like.group("key")
            issues.append(CitationIssue(key, "malformed-page", "reference definition must end with #page=<positive integer>"))
            invalid_keys.add(key)
    return out, issues, invalid_keys


def _row_for_definition(conn, defn: ReferenceDefinition, report_path: Path, root: Path):
    source_path = normalise_source_path(root, defn.path, base=report_path.resolve().parent)
    return source_row_for_path(conn, source_path)


def verify_report(conn, report_path: Path, root: Path, *, source_links_path: Path | None = None, source_links_root: Path | None = None) -> ReportVerification:
    report_path = Path(report_path)
    root = Path(root).resolve()
    lines = _prose_lines(report_path.read_text(encoding="utf-8").splitlines())
    definitions, parse_issues, invalid_definition_keys = _parse_definitions(lines)
    result = ReportVerification(definitions=definitions)
    result.citation_issues.extend(parse_issues)
    for line in lines:
        for match in _CITATION_RE.finditer(line):
            result.citation_keys_used.add(match.group("key"))
    for key in sorted(result.citation_keys_used):
        definition = result.definitions.get(key)
        if key in invalid_definition_keys:
            continue
        if definition is None:
            result.citation_issues.append(CitationIssue(key, "missing-definition", "no reference definition found"))
            continue
        if definition.page <= 0:
            result.citation_issues.append(CitationIssue(key, "bad-page", "page must be positive"))
            continue
        try:
            source_row = _row_for_definition(conn, definition, report_path, root)
        except PathAuthorityError as exc:
            result.citation_issues.append(CitationIssue(key, "path-outside-root", str(exc)))
            continue
        if source_row is None:
            result.citation_issues.append(CitationIssue(key, "unindexed-path", f"{definition.path} is not indexed"))
            continue
        page_row = conn.execute(
            "SELECT physical_page FROM pages WHERE source_pk = ? AND physical_page = ?",
            (source_row["source_pk"], definition.page),
        ).fetchone()
        if page_row is None:
            result.citation_issues.append(CitationIssue(key, "page-not-indexed", f"page {definition.page} is not indexed for {source_row['path']}"))
    paragraph_keys: list[str] = []
    paragraph_break_pending = False
    index = 0
    while index < len(lines):
        line = lines[index]
        quote_match = _BLOCKQUOTE_RE.match(line)
        if quote_match:
            quote_parts = [quote_match.group("quote")]
            while index + 1 < len(lines) and _BLOCKQUOTE_RE.match(lines[index + 1]):
                index += 1
                quote_parts.append(_BLOCKQUOTE_RE.match(lines[index]).group("quote"))
            quote_parts[0] = quote_parts[0].lstrip()
            quote_parts[-1] = quote_parts[-1].rstrip()
            if quote_parts[0].startswith('"'):
                quote_parts[0] = quote_parts[0][1:]
            if quote_parts[-1].endswith('"'):
                quote_parts[-1] = quote_parts[-1][:-1]
            quote = "\n".join(quote_parts)
            viable: list[tuple[str, object, ReferenceDefinition]] = []
            for key in dict.fromkeys(paragraph_keys):
                definition = result.definitions.get(key)
                if definition is None or key in invalid_definition_keys or definition.page <= 0:
                    continue
                try:
                    source_row = _row_for_definition(conn, definition, report_path, root)
                except PathAuthorityError:
                    continue
                if source_row is None:
                    continue
                page_row = conn.execute(
                    "SELECT physical_page FROM pages WHERE source_pk = ? AND physical_page = ?",
                    (source_row["source_pk"], definition.page),
                ).fetchone()
                if page_row is not None:
                    viable.append((key, source_row, definition))
            if not quote.strip() or len(viable) != 1:
                result.quote_results.append(QuoteVerification("structural-error", 0, quote))
            else:
                key, source_row, definition = viable[0]
                best = verify_quote(conn, source_row["path"], definition.page, quote)
                best = QuoteVerification(best.status, best.physical_page, best.quote, key, source_row["path"])
                result.quote_results.append(best)
            index += 1
            continue
        if line.strip() == "":
            paragraph_break_pending = True
            index += 1
            continue
        citations = [m.group("key") for m in _CITATION_RE.finditer(line)]
        if re.match(r"^\s{0,3}(?:#{1,6}\s|[-*_](?:\s*[-*_]){2,}\s*$|(?:[-+*]|\d+[.)])\s+)", line):
            paragraph_keys = []
        elif paragraph_break_pending:
            paragraph_keys = citations
        else:
            paragraph_keys.extend(citations)
        paragraph_break_pending = False
        index += 1
    if source_links_path is not None:
        registry_root = Path(source_links_root or root).resolve()
        registry, registry_issues = _load_source_links(source_links_path, registry_root)
        result.source_link_issues.extend(registry_issues)
        for key in sorted(result.citation_keys_used):
            definition = result.definitions.get(key)
            if not definition:
                continue
            try:
                source_row = _row_for_definition(conn, definition, report_path, root)
            except PathAuthorityError:
                continue
            if source_row is None:
                continue
            source_abs = (root / source_row["path"]).resolve()
            entries = registry.get(source_abs, [])
            if not entries:
                result.source_link_issues.append(f"no source-link entry for {source_row['path']} in {source_links_path}")
            elif len(entries) > 1:
                result.source_link_issues.append(f"{source_row['path']} has {len(entries)} ambiguous entries in {source_links_path}")
            else:
                entry_abs = (registry_root / _normalise_relative_path(entries[0].local_path)).resolve()
                if entry_abs != source_abs:
                    result.source_link_issues.append(f"{entries[0].local_path} in {source_links_path} does not agree with the database")
    return result


def _load_source_links(path: Path, source_links_root: Path) -> tuple[dict[Path, list[SourceLinkEntry]], list[str]]:
    return load_source_links(path, source_links_root)


def _prose_lines(lines: list[str]) -> list[str]:
    """Remove non-prose regions before citation and quote scanning."""
    output: list[str] = []
    fenced = False
    fence_marker = ""
    fence_length = 0
    in_comment = False
    for raw in lines:
        line = raw
        fence = _FENCE_RE.match(line)
        if fenced:
            if (
                fence
                and fence.group("marker")[0] == fence_marker
                and len(fence.group("marker")) >= fence_length
                and not fence.group("suffix").strip()
            ):
                fenced = False
            continue
        if fence:
            fenced = True
            fence_marker = fence.group("marker")[0]
            fence_length = len(fence.group("marker"))
            continue
        if line.startswith("    ") or line.startswith("\t"):
            continue
        while in_comment or "<!--" in line:
            if in_comment:
                end = line.find("-->")
                if end < 0:
                    line = ""
                    break
                line = line[end + 3 :]
                in_comment = False
            else:
                start = line.find("<!--")
                end = line.find("-->", start + 4)
                if end < 0:
                    line = line[:start]
                    in_comment = True
                    break
                line = line[:start] + line[end + 3 :]
        output.append(_strip_inline_code(line))
    return output


def _strip_inline_code(line: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(line):
        if line[index] != "`":
            output.append(line[index])
            index += 1
            continue
        marker = line[index]
        end = index
        while end < len(line) and line[end] == marker:
            end += 1
        length = end - index
        search = end
        close_end = None
        while search < len(line):
            candidate = line.find(marker, search)
            if candidate < 0:
                break
            run_end = candidate
            while run_end < len(line) and line[run_end] == marker:
                run_end += 1
            if run_end - candidate == length:
                close_end = run_end
                break
            search = run_end
        if close_end is None:
            output.extend(line[index:end])
            index = end
            continue
        index = close_end
    return "".join(output)
