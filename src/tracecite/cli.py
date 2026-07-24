"""Command-line interface for table normalisation and inspection-site export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .tables import (
    TableContext,
    TableNormalisationError,
    augment_document_with_embedding_text,
    export_embedding_site,
    normalise_document_tables,
    normalise_html_table,
    normalise_pandoc_table,
    render_debug_markdown,
)
from .docs import (
    author_docs,
    build_docs,
    check_docs,
    doctor_docs_index,
    load_docs_contract,
    search_docs_index,
    stage_docs,
    sync_docs_index,
)

EVIDENCE_COMMANDS = {"sync", "search", "page", "verify", "prune", "doctor"}

DEFAULT_LIMIT = 10
DEFAULT_FTS_LIMIT = 50
DEFAULT_VECTOR_LIMIT = 50
DEFAULT_MAX_CHUNK_CHARS = 1200
DEFAULT_OCR_LANG = "eng"


def _add_evidence_common_args(
    parser: argparse.ArgumentParser,
    *,
    root_required: bool = False,
    database_required: bool = True,
) -> None:
    del root_required, database_required
    parser.add_argument("--config", type=Path, default=argparse.SUPPRESS, help="TraceCite profile TOML.")
    parser.add_argument("--root", type=Path, default=None, help="Source root directory.")
    parser.add_argument("--database", type=Path, default=None, help="SQLite database path.")
    parser.add_argument("--model-cache-dir", type=Path, default=None)
    parser.add_argument("--manifest", dest="manifests", action="append", type=Path, default=[])


def _add_evidence_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    sync_parser = subparsers.add_parser("sync", help="Synchronise selected sources into the database.")
    _add_evidence_common_args(sync_parser, root_required=True)
    sync_parser.add_argument("path", nargs="?", default=None, help="Only sync this one root-relative source path.")
    sync_parser.add_argument("--full", action="store_true", help="Reparse and rechunk every source.")
    sync_parser.add_argument("--reembed", action="store_true", help="Force embedding regeneration.")
    sync_parser.add_argument("--max-chunk-chars", type=int, default=DEFAULT_MAX_CHUNK_CHARS)
    sync_parser.add_argument("--no-assets", action="store_true", help="Skip PDF page render/crop generation.")
    sync_parser.add_argument("--ocr-lang", default=DEFAULT_OCR_LANG)

    search_parser = subparsers.add_parser("search", help="Hybrid FTS + vector search.")
    _add_evidence_common_args(search_parser)
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    search_parser.add_argument("--fts-limit", type=int, default=DEFAULT_FTS_LIMIT)
    search_parser.add_argument("--vector-limit", type=int, default=DEFAULT_VECTOR_LIMIT)

    page_parser = subparsers.add_parser("page", help="Retrieve one physical page's retained text.")
    _add_evidence_common_args(page_parser)
    page_parser.add_argument("source_path")
    page_parser.add_argument("page", type=int)

    verify_parser = subparsers.add_parser("verify", help="Verify quotes or Markdown reports.")
    verify_subparsers = verify_parser.add_subparsers(dest="verify_command", required=True)
    quote_parser = verify_subparsers.add_parser("quote", help="Verify a quotation against retained page text.")
    _add_evidence_common_args(quote_parser)
    quote_parser.add_argument("source_path")
    quote_parser.add_argument("page", type=int)
    quote_parser.add_argument("quote")
    report_parser = verify_subparsers.add_parser("report", help="Verify a Markdown report's citations and quotes.")
    _add_evidence_common_args(report_parser)
    report_parser.add_argument("report_path", type=Path)
    report_parser.add_argument("--source-links", type=Path, default=None)
    report_parser.add_argument("--source-links-root", type=Path, default=None)

    prune_parser = subparsers.add_parser("prune", help="Preview or apply removal of unselected indexed paths.")
    _add_evidence_common_args(prune_parser)
    prune_parser.add_argument("--apply", action="store_true", dest="apply")
    prune_parser.add_argument(
        "--all",
        action="store_true",
        dest="prune_all",
        help="Explicitly select no retained paths, so every indexed source is planned for pruning.",
    )

    doctor_parser = subparsers.add_parser("doctor", help="Integrity checks: relational rows, FTS, vectors, assets.")
    _add_evidence_common_args(doctor_parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tracecite")
    parser.add_argument("--config", type=Path, default=None, help="TraceCite profile TOML.")
    parser.add_argument("--version", action="version", version="TraceCite 0.4.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    table = subparsers.add_parser("table", help="Normalise one table")
    table_sub = table.add_subparsers(dest="table_command", required=True)
    normalise = table_sub.add_parser(
        "normalise", help="Normalise one Markdown or HTML table"
    )
    normalise.add_argument("input", help="Input path or '-' for standard input")
    normalise.add_argument(
        "--from",
        dest="source_format",
        choices=["auto", "pandoc", "html"],
        default="auto",
    )
    normalise.add_argument(
        "--to",
        dest="target_format",
        choices=["text", "json", "canonical-markdown", "debug-markdown"],
        default="text",
    )
    normalise.add_argument("--output", type=Path)
    normalise.add_argument("--document-path")
    normalise.add_argument("--source-code-path")
    normalise.add_argument("--caption")
    normalise.add_argument("--table-id")
    normalise.add_argument("--ordering")
    normalise.add_argument("--strict", action="store_true")
    normalise.add_argument("--pandoc")
    normalise.add_argument("--allow-pipe-fallback", action="store_true")

    document = subparsers.add_parser(
        "document", help="Normalise every table in one document"
    )
    document_sub = document.add_subparsers(dest="document_command", required=True)
    document_normalise = document_sub.add_parser(
        "normalise", help="Normalise document tables"
    )
    document_normalise.add_argument("input", type=Path)
    document_normalise.add_argument(
        "--to",
        dest="target_format",
        choices=["jsonl", "embedding-markdown", "summary"],
        default="summary",
    )
    document_normalise.add_argument("--output", type=Path)
    document_normalise.add_argument("--source-code-path")
    document_normalise.add_argument("--strict", action="store_true")
    document_normalise.add_argument("--pandoc")
    document_normalise.add_argument("--allow-pipe-fallback", action="store_true")

    prepare = subparsers.add_parser(
        "prepare",
        help="Prepare table records and optionally keep a complete embedding-Markdown website",
    )
    prepare.add_argument("source_root", type=Path)
    prepare.add_argument("--project-config", type=Path)
    prepare.add_argument(
        "--project-profile",
        help="Merge _quarto-<profile>.yml into the copied inspection-site configuration",
    )
    prepare.add_argument("--source-project", type=Path)
    prepare.add_argument(
        "--keep-embedding-markdown",
        type=Path,
        metavar="DIR",
        required=True,
        help="Copy the complete retained-Markdown website to DIR and append normalised table text",
    )
    prepare.add_argument("--render-embedding-site", action="store_true")
    prepare.add_argument("--debug-tables", action="store_true")
    prepare.add_argument("--quarto")
    prepare.add_argument("--pandoc")
    prepare.add_argument("--strict-tables", action="store_true")
    prepare.add_argument("--allow-pipe-fallback", action="store_true")
    prepare.add_argument("--no-clean", action="store_true")

    docs_parser = subparsers.add_parser("docs", help="Build documentation")
    docs_sub = docs_parser.add_subparsers(dest="docs_command", required=True)
    docs_build = docs_sub.add_parser("build", help="Build a Quarto documentation project")
    docs_build.add_argument("project", type=Path)
    docs_build.add_argument("--docs-config", type=Path, default=None)
    docs_build.add_argument("--repo-root", type=Path, default=Path.cwd())
    docs_build.add_argument("--only", choices=["python", "julia"])
    docs_build.add_argument("--quarto")
    docs_build.add_argument("--no-embedding-site", action="store_true")
    docs_build.add_argument("--no-render-embedding-site", action="store_true")
    docs_build.add_argument("--strict-tables", action="store_true")
    docs_build.add_argument("--check-retained", action="store_true")
    docs_stage = docs_sub.add_parser("stage", help="Stage local or public source links")
    docs_stage.add_argument("--docs-config", type=Path, required=True)
    docs_stage.add_argument("--repo-root", type=Path, default=Path.cwd())
    docs_stage.add_argument("--target", choices=["local", "public"], required=True)
    for name in ("author", "check"):
        mode = docs_sub.add_parser(name, help=f"{name.title()} documentation outputs")
        mode.add_argument("--docs-config", type=Path, required=True)
        mode.add_argument("--repo-root", type=Path, default=Path.cwd())
    for name, help_text in (
        ("index", "Build the index-input mirror and synchronise the documentation index"),
        ("search", "Hybrid FTS + vector search over the documentation index"),
        ("doctor", "Integrity checks for the documentation index profile"),
    ):
        command = docs_sub.add_parser(name, help=help_text)
        command.add_argument("--docs-config", type=Path, required=True)
        command.add_argument("--repo-root", type=Path, default=Path.cwd())
    docs_search = docs_sub.choices["search"]
    docs_search.add_argument("query")
    docs_search.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    docs_search.add_argument("--fts-limit", type=int, default=DEFAULT_FTS_LIMIT)
    docs_search.add_argument("--vector-limit", type=int, default=DEFAULT_VECTOR_LIMIT)

    check = subparsers.add_parser(
        "check", help="Strictly validate generated Markdown tables"
    )
    check.add_argument("path", type=Path)
    check.add_argument("--pandoc")
    check.add_argument("--allow-pipe-fallback", action="store_true")
    check.add_argument("--debug-tables", action="store_true")
    _add_evidence_parsers(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "table":
            return _table_normalise(args)
        if args.command == "document":
            return _document_normalise(args)
        if args.command == "prepare":
            return _prepare(args)
        if args.command == "docs":
            if args.docs_command == "stage":
                return _docs_stage(args)
            if args.docs_command == "author":
                return _docs_mode(args, author_docs)
            if args.docs_command == "check":
                return _docs_mode(args, check_docs)
            if args.docs_command == "index":
                return _docs_index(args)
            if args.docs_command == "search":
                return _docs_search(args)
            if args.docs_command == "doctor":
                return _docs_doctor(args)
            return _docs_build(args)
        if args.command == "check":
            return _check(args)
        if args.command in EVIDENCE_COMMANDS:
            return _evidence(args)
    except ModuleNotFoundError as error:
        if _is_missing_evidence_dependency(error):
            print(
                "tracecite: evidence commands require the optional evidence dependencies; "
                "install with tracecite[evidence]",
                file=sys.stderr,
            )
            return 2
        raise
    except (
        FileNotFoundError,
        RuntimeError,
        TableNormalisationError,
        ValueError,
    ) as error:
        print(f"tracecite: {error}", file=sys.stderr)
        return 2
    return 1


def _is_missing_evidence_dependency(error: ModuleNotFoundError) -> bool:
    if "tracecite[evidence]" in str(error):
        return True
    return (error.name or "").split(".", 1)[0] in {
        "fitz",
        "huggingface_hub",
        "sentence_transformers",
        "sqlite_vec",
    }


def _evidence(args: argparse.Namespace) -> int:
    from .evidence.commands import dispatch

    return dispatch(args)


def _docs_build(args: argparse.Namespace) -> int:
    if args.docs_config is not None:
        load_docs_contract(args.docs_config, repo_root=args.repo_root)
    result = build_docs(
        args.project,
        only=args.only,
        quarto=args.quarto,
        inspection=not args.no_embedding_site,
        render_inspection=not args.no_render_embedding_site,
        strict_tables=args.strict_tables,
        check_retained=args.check_retained,
    )
    print(f"Documentation build: {result.selection.variant}")
    print(f"Documentation site: {result.output_root}")
    print(f"Retained Markdown pages: {result.retained_count}")
    if result.inspection:
        print(f"Embedding Markdown site: {result.inspection.output_root}")
        print(f"Pages copied: {result.inspection.page_count}")
        print(f"Tables normalised: {result.inspection.table_count}")
        if result.inspection.rendered_site:
            print(f"Rendered inspection site: {result.inspection.rendered_site}")
    if args.check_retained:
        if result.changed_retained:
            print("Retained Markdown changed:")
            print("\n".join(f"- {path}" for path in result.changed_retained))
            return 1
        print("Retained Markdown is fresh.")
    return 0


def _docs_stage(args: argparse.Namespace) -> int:
    contract = load_docs_contract(args.docs_config, repo_root=args.repo_root)
    result = stage_docs(contract, target=args.target, repo_root=args.repo_root)
    print(f"Documentation staging target: {result.target}")
    print(f"Documentation staging root: {result.staged_root}")
    print(f"Changed Markdown files: {len(result.changed_files)}")
    return 0


def _docs_mode(args: argparse.Namespace, operation) -> int:
    contract = load_docs_contract(args.docs_config, repo_root=args.repo_root)
    result = operation(contract, config_path=args.docs_config, repo_root=args.repo_root)
    print(f"Documentation mode: {result.mode}")
    print(f"Manifest: {result.manifest_path}")
    if result.diagnostics:
        print("\n".join(f"- {item}" for item in result.diagnostics), file=sys.stderr)
    return 0 if result.ok else 1


def _docs_index(args: argparse.Namespace) -> int:
    try:
        contract = load_docs_contract(args.docs_config, repo_root=args.repo_root)
        result = sync_docs_index(contract, repo_root=args.repo_root)
    except ModuleNotFoundError as error:
        return _missing_evidence_exit(error)
    report = result.sync_report
    print(f"Documentation index input: {result.profile.input_root}")
    print(f"Documentation index database: {result.profile.database_path}")
    print(f"Tables normalised: {result.tables_normalized}")
    print(f"status: {report.status}")
    print(f"added: {report.sources_added}")
    print(f"unchanged: {len(report.sources_unchanged)} source(s)")
    print(f"embeddings generated: {report.embeddings_generated}")
    return 0 if report.status == "ok" else 1


def _docs_search(args: argparse.Namespace) -> int:
    try:
        contract = load_docs_contract(args.docs_config, repo_root=args.repo_root)
        results = search_docs_index(
            contract,
            args.query,
            repo_root=args.repo_root,
            limit=args.limit,
            fts_limit=args.fts_limit,
            vector_limit=args.vector_limit,
        )
    except ModuleNotFoundError as error:
        return _missing_evidence_exit(error)
    print(json.dumps(results, indent=2))
    return 0


def _docs_doctor(args: argparse.Namespace) -> int:
    try:
        contract = load_docs_contract(args.docs_config, repo_root=args.repo_root)
        issues = doctor_docs_index(contract, repo_root=args.repo_root)
    except ModuleNotFoundError as error:
        return _missing_evidence_exit(error)
    for issue in issues:
        print(f"ISSUE: {issue}")
    if not issues:
        print("doctor: no issues found")
    return 0 if not issues else 1


def _missing_evidence_exit(error: ModuleNotFoundError) -> int:
    if _is_missing_evidence_dependency(error):
        print(
            "tracecite: evidence commands require the optional evidence dependencies; "
            "install with tracecite[evidence]",
            file=sys.stderr,
        )
        return 2
    raise error


def _table_normalise(args: argparse.Namespace) -> int:
    source = (
        sys.stdin.read()
        if args.input == "-"
        else Path(args.input).read_text(encoding="utf-8")
    )
    context = TableContext(
        document_path=args.document_path
        or ("<stdin>" if args.input == "-" else args.input),
        source_code_path=args.source_code_path,
        caption=args.caption,
        table_id=args.table_id,
        ordering=args.ordering,
    )
    source_format = args.source_format
    if source_format == "auto":
        source_format = "html" if "<table" in source.lower() else "pandoc"

    if source_format == "html":
        table = normalise_html_table(
            source,
            context=context,
            strict=args.strict,
            pandoc=args.pandoc,
        )
    else:
        table = normalise_pandoc_table(
            source,
            context=context,
            strict=args.strict,
            pandoc=args.pandoc,
            allow_pipe_fallback=args.allow_pipe_fallback,
        )

    output = {
        "text": table.normalised_text,
        "json": table.to_json(),
        "canonical-markdown": table.canonical_markdown,
        "debug-markdown": render_debug_markdown(table),
    }[args.target_format]
    _write_output(output.rstrip() + "\n", args.output)
    return 0


def _document_normalise(args: argparse.Namespace) -> int:
    source = args.input.read_text(encoding="utf-8")
    if args.target_format == "embedding-markdown":
        result = augment_document_with_embedding_text(
            source,
            document_path=args.input.as_posix(),
            source_code_path=args.source_code_path,
            strict=args.strict,
            pandoc=args.pandoc,
            allow_pipe_fallback=args.allow_pipe_fallback,
        )
        _write_output(result.markdown, args.output)
        return 0

    tables = normalise_document_tables(
        source,
        document_path=args.input.as_posix(),
        source_code_path=args.source_code_path,
        strict=args.strict,
        pandoc=args.pandoc,
        allow_pipe_fallback=args.allow_pipe_fallback,
    )
    if args.target_format == "jsonl":
        output = "".join(
            json.dumps(table.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
            for table in tables
        )
    else:
        lines = [f"Tables: {len(tables)}"]
        for table in tables:
            warning_count = sum(
                item.severity == "warning" for item in table.diagnostics
            )
            error_count = sum(item.severity == "error" for item in table.diagnostics)
            lines.append(
                f"- {table.table_id}: {len(table.rows)} row(s), {len(table.headers)} column(s), "
                f"{warning_count} warning(s), {error_count} error(s)"
            )
        output = "\n".join(lines) + "\n"
    _write_output(output, args.output)
    return 0


def _prepare(args: argparse.Namespace) -> int:
    result = export_embedding_site(
        args.source_root,
        args.keep_embedding_markdown,
        project_config=args.project_config,
        project_profile=args.project_profile,
        source_project=args.source_project,
        strict=args.strict_tables,
        pandoc=args.pandoc,
        allow_pipe_fallback=args.allow_pipe_fallback,
        render=args.render_embedding_site,
        quarto=args.quarto,
        clean=not args.no_clean,
    )
    print(f"Embedding Markdown site: {result.output_root}")
    print(f"Pages copied: {result.page_count}")
    print(f"Tables normalised: {result.table_count}")
    if result.rendered_site:
        print(f"Rendered inspection site: {result.rendered_site}")
    if args.debug_tables:
        _print_table_debug(result.output_root / "_tracecite" / "tables.jsonl")
    return 0


def _check(args: argparse.Namespace) -> int:
    paths = [args.path] if args.path.is_file() else _markdown_paths(args.path)
    check_root = args.path.parent if args.path.is_file() else args.path
    failures = 0
    tables = 0
    for path in paths:
        source = path.read_text(encoding="utf-8")
        try:
            document_path = path.relative_to(check_root).as_posix()
        except ValueError:
            document_path = path.as_posix()
        try:
            found = normalise_document_tables(
                source,
                document_path=document_path,
                strict=True,
                pandoc=args.pandoc,
                allow_pipe_fallback=args.allow_pipe_fallback,
            )
        except TableNormalisationError as error:
            failures += 1
            print(f"FAIL {path}: {error}")
            continue
        tables += len(found)
        print(f"OK   {path}: {len(found)} table(s)")
        if args.debug_tables:
            for table in found:
                print(
                    f"     {table.table_id}: {len(table.rows)} row(s), "
                    f"{len(table.headers)} column(s), source={table.source_format}"
                )
                for diagnostic in table.diagnostics:
                    print(
                        f"       {diagnostic.severity}:{diagnostic.code}: "
                        f"{diagnostic.message}"
                    )
    print(f"Checked {len(paths)} file(s), {tables} table(s), {failures} failure(s)")
    return 1 if failures else 0


def _write_output(text: str, path: Path | None) -> None:
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _markdown_paths(root: Path) -> list[Path]:
    excluded = {".tracecite", "_tracecite", ".quarto", "site_libs", "_site"}
    return [
        path
        for path in sorted(root.rglob("*.md"))
        if not any(part in excluded for part in path.relative_to(root).parts)
    ]


def _print_table_debug(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        table = json.loads(line)
        print(
            f"DEBUG {table['table_id']}: {len(table['rows'])} row(s), "
            f"{len(table['headers'])} column(s), source={table['source_format']}"
        )
        for diagnostic in table.get("diagnostics", []):
            print(
                f"      {diagnostic['severity']}:{diagnostic['code']}: "
                f"{diagnostic['message']}"
            )


if __name__ == "__main__":
    raise SystemExit(main())
