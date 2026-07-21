from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_LIMIT = 10
DEFAULT_FTS_LIMIT = 50
DEFAULT_VECTOR_LIMIT = 50
DEFAULT_MAX_CHUNK_CHARS = 1200
DEFAULT_OCR_LANG = "eng"


def _add_common_args(parser: argparse.ArgumentParser, *, root_required: bool = False, database_required: bool = True) -> None:
    parser.add_argument("--config", type=Path, default=None, help="TraceCite profile TOML.")
    parser.add_argument("--root", type=Path, default=None, help="Source root directory.")
    parser.add_argument("--database", type=Path, default=None, help="SQLite database path.")
    parser.add_argument("--model-cache-dir", type=Path, default=None)
    parser.add_argument("--manifest", dest="manifests", action="append", type=Path, default=[])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tracecite", description="TraceCite local evidence indexer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="Synchronise selected sources into the database.")
    _add_common_args(sync_parser, root_required=True)
    sync_parser.add_argument("path", nargs="?", default=None, help="Only sync this one root-relative source path.")
    sync_parser.add_argument("--full", action="store_true", help="Reparse and rechunk every source.")
    sync_parser.add_argument("--reembed", action="store_true", help="Force embedding regeneration.")
    sync_parser.add_argument("--max-chunk-chars", type=int, default=DEFAULT_MAX_CHUNK_CHARS)
    sync_parser.add_argument("--no-assets", action="store_true", help="Skip PDF page render/crop generation.")
    sync_parser.add_argument("--ocr-lang", default=DEFAULT_OCR_LANG)

    search_parser = subparsers.add_parser("search", help="Hybrid FTS + vector search.")
    _add_common_args(search_parser)
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    search_parser.add_argument("--fts-limit", type=int, default=DEFAULT_FTS_LIMIT)
    search_parser.add_argument("--vector-limit", type=int, default=DEFAULT_VECTOR_LIMIT)

    page_parser = subparsers.add_parser("page", help="Retrieve one physical page's retained text.")
    _add_common_args(page_parser)
    page_parser.add_argument("source_path")
    page_parser.add_argument("page", type=int)

    verify_parser = subparsers.add_parser("verify", help="Verify quotes or Markdown reports.")
    verify_subparsers = verify_parser.add_subparsers(dest="verify_command", required=True)
    quote_parser = verify_subparsers.add_parser("quote", help="Verify a quotation against retained page text.")
    _add_common_args(quote_parser)
    quote_parser.add_argument("source_path")
    quote_parser.add_argument("page", type=int)
    quote_parser.add_argument("quote")
    report_parser = verify_subparsers.add_parser("report", help="Verify a Markdown report's citations and quotes.")
    _add_common_args(report_parser)
    report_parser.add_argument("report_path", type=Path)
    report_parser.add_argument("--source-links", type=Path, default=None)
    report_parser.add_argument("--source-links-root", type=Path, default=None)

    prune_parser = subparsers.add_parser("prune", help="Preview or apply removal of unselected indexed paths.")
    _add_common_args(prune_parser)
    prune_parser.add_argument("--apply", action="store_true", dest="apply")
    prune_parser.add_argument(
        "--all",
        action="store_true",
        dest="prune_all",
        help="Explicitly select no retained paths, so every indexed source is planned for pruning.",
    )

    doctor_parser = subparsers.add_parser("doctor", help="Integrity checks: relational rows, FTS, vectors, assets.")
    _add_common_args(doctor_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from .commands import dispatch
    return dispatch(args)


if __name__ == "__main__":
    raise SystemExit(main())
