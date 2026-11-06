"""Command-line interface for evidence retrieval and the bundled agent skills."""

from __future__ import annotations

import argparse
import functools
import shutil
import sys
from pathlib import Path

from . import __version__

DEFAULT_LIMIT = 10
DEFAULT_FTS_LIMIT = 50
DEFAULT_VECTOR_LIMIT = 50

LIMIT_HELP = "Number of results to return (default: %(default)s)."
FTS_LIMIT_HELP = "Full-text candidates ranked before fusion (default: %(default)s)."
VECTOR_LIMIT_HELP = "Vector candidates ranked before fusion (default: %(default)s)."


def _add_evidence_common_args(parser: argparse.ArgumentParser, command: str) -> None:
    parser.set_defaults(handler=functools.partial(_evidence, command))
    parser.add_argument(
        "--config", type=Path, default=argparse.SUPPRESS, help="TraceCite profile TOML."
    )
    parser.add_argument(
        "--root", type=Path, default=None, help="Source root directory."
    )
    parser.add_argument(
        "--database", type=Path, default=None, help="SQLite database path."
    )
    parser.add_argument("--model-cache-dir", type=Path, default=None)
    parser.add_argument(
        "--manifest", dest="manifests", action="append", type=Path, default=[]
    )


def _add_evidence_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    sync_parser = subparsers.add_parser(
        "sync", help="Synchronise selected sources into the database."
    )
    _add_evidence_common_args(sync_parser, "cmd_sync")
    sync_parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Only sync this one root-relative source path.",
    )
    sync_parser.add_argument(
        "--full", action="store_true", help="Reparse and rechunk every source."
    )
    sync_parser.add_argument(
        "--reembed", action="store_true", help="Force embedding regeneration."
    )
    sync_parser.add_argument("--max-chunk-chars", type=int, default=None)
    sync_parser.add_argument(
        "--no-assets", action="store_true", help="Skip PDF page render/crop generation."
    )
    sync_parser.add_argument(
        "--json", action="store_true", help="Print the sync report as JSON."
    )

    search_parser = subparsers.add_parser("search", help="Hybrid FTS + vector search.")
    _add_evidence_common_args(search_parser, "cmd_search")
    search_parser.add_argument("query")
    search_parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, help=LIMIT_HELP
    )
    search_parser.add_argument(
        "--fts-limit", type=int, default=DEFAULT_FTS_LIMIT, help=FTS_LIMIT_HELP
    )
    search_parser.add_argument(
        "--vector-limit", type=int, default=DEFAULT_VECTOR_LIMIT, help=VECTOR_LIMIT_HELP
    )
    search_parser.add_argument(
        "--source-type",
        dest="source_types",
        action="append",
        choices=["pdf", "markdown", "workbook"],
        default=None,
        help="Restrict results to one or more source types (repeatable).",
    )
    search_parser.add_argument(
        "--lexical-only",
        action="store_true",
        help="Use only full-text search and skip loading the embedding model.",
    )

    page_parser = subparsers.add_parser(
        "page", help="Retrieve retained text for one physical page or selector."
    )
    _add_evidence_common_args(page_parser, "cmd_page")
    page_parser.add_argument("source_path")
    page_parser.add_argument("page", nargs="?", default=None)
    page_parser.add_argument("--format", choices=["text", "json"], default="text")

    extract_parser = subparsers.add_parser(
        "extract-pages", help="Extract selected pages into a derivative PDF."
    )
    _add_evidence_common_args(extract_parser, "cmd_extract_pages")
    extract_parser.add_argument("source_path")
    extract_parser.add_argument("page", nargs="?", default=None)
    extract_parser.add_argument("--output-dir", type=Path, required=True)

    verify_parser = subparsers.add_parser(
        "verify", help="Verify quotes or Markdown reports."
    )
    verify_subparsers = verify_parser.add_subparsers(
        dest="verify_command", required=True
    )
    quote_parser = verify_subparsers.add_parser(
        "quote", help="Verify a quotation against retained page text."
    )
    _add_evidence_common_args(quote_parser, "cmd_verify_quote")
    quote_parser.add_argument("source_path")
    quote_parser.add_argument(
        "page", help="Physical page or contiguous page range, such as 4 or 4-5."
    )
    quote_parser.add_argument("quote")
    report_parser = verify_subparsers.add_parser(
        "report", help="Verify a Markdown report's citations and quotes."
    )
    _add_evidence_common_args(report_parser, "cmd_verify_report")
    report_parser.add_argument("report_path", type=Path)
    report_parser.add_argument("--source-links", type=Path, default=None)
    report_parser.add_argument("--source-links-root", type=Path, default=None)

    prune_parser = subparsers.add_parser(
        "prune",
        help="Preview or apply removal of indexed paths that are unselected or missing under the root.",
    )
    _add_evidence_common_args(prune_parser, "cmd_prune")
    prune_parser.add_argument("--apply", action="store_true", dest="apply")
    prune_parser.add_argument(
        "--all",
        action="store_true",
        dest="prune_all",
        help="Explicitly select no retained paths, so every indexed source is planned for pruning.",
    )

    doctor_parser = subparsers.add_parser(
        "doctor", help="Integrity checks: relational rows, FTS, vectors, assets."
    )
    _add_evidence_common_args(doctor_parser, "cmd_doctor")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tracecite")
    parser.add_argument(
        "--config", type=Path, default=None, help="TraceCite profile TOML."
    )
    parser.add_argument(
        "--version", action="version", version=f"TraceCite {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    skills = subparsers.add_parser("skills", help="Install the bundled agent skills")
    skills_sub = skills.add_subparsers(dest="skills_command", required=True)
    skills_install = skills_sub.add_parser(
        "install", help="Copy the bundled agent skills into a skills directory"
    )
    skills_install.set_defaults(handler=_skills_install)
    skills_install.add_argument("--target", type=Path, default=Path(".agents/skills"))
    _add_evidence_parsers(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except ModuleNotFoundError as error:
        if _is_missing_evidence_dependency(error):
            print(
                "tracecite: evidence commands require the optional evidence dependencies; "
                "install with tracecite[evidence]",
                file=sys.stderr,
            )
            return 2
        raise
    except (OSError, RuntimeError, ValueError) as error:
        print(f"tracecite: {error}", file=sys.stderr)
        return 2


def _is_missing_evidence_dependency(error: ModuleNotFoundError) -> bool:
    if "tracecite[evidence]" in str(error):
        return True
    return (error.name or "").split(".", 1)[0] in {
        "pymupdf",
        "huggingface_hub",
        "sentence_transformers",
        "sqlite_vec",
    }


def _evidence(command: str, args: argparse.Namespace) -> int:
    from .evidence import commands

    return commands.dispatch(getattr(commands, command), args)


def _skills_install(args: argparse.Namespace) -> int:
    for skill in sorted((Path(__file__).parent / "skills").iterdir()):
        if not skill.is_dir():
            continue
        destination = args.target / skill.name
        if destination.resolve() == skill.resolve():
            print(f"Skipped {skill.name}: {destination} is the bundled source")
            continue
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(skill, destination)
        print(f"Installed {skill.name} -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
