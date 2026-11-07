from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sqlite3
import sys
from collections import defaultdict
from contextlib import closing, contextmanager
from pathlib import Path

from . import config as config_module
from . import schema
from .page_extraction import PageExtractionError
from .page_output import PageOutputError
from .paths import PathAuthorityError, normalise_source_path, source_row_for_path

RRF_K = 60


def _json(value, indent: int | None = None) -> str:
    return json.dumps(value, indent=indent, ensure_ascii=False)


def _require(value, flag: str):
    if value is None:
        raise SystemExit(f"error: {flag} is required for this command")
    return value


@contextmanager
def _database(database: Path | None, *, read_only: bool = True):
    """Open an existing database, check its schema, and close it on exit."""
    with closing(
        schema.connect_existing(_require(database, "--database"), read_only=read_only)
    ) as conn:
        schema.ensure_schema(conn)
        yield conn


def _indexed_source(conn, args: argparse.Namespace):
    """Return ``args.source_path`` relative to the root, and its source row or None."""
    root = Path(args.root or Path.cwd()).resolve()
    source_path = normalise_source_path(root, args.source_path)
    return source_path, source_row_for_path(conn, source_path)


def _resolve_runtime_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.config is None:
        return args
    profile = config_module.load_profile(args.config)
    if args.root is None:
        args.root = profile.root
    if args.database is None:
        args.database = profile.database
    if args.model_cache_dir is None:
        args.model_cache_dir = profile.model_cache_dir
    args.manifests = [*profile.manifests, *args.manifests]
    return args


def cmd_sync(args: argparse.Namespace) -> int:
    from . import sync as sync_module

    options = sync_module.SyncOptions(
        generate_assets=not args.no_assets, full=args.full, reembed=args.reembed
    )
    if args.max_chunk_chars is not None:
        options.max_chunk_chars = args.max_chunk_chars
    only_paths = {Path(args.path).as_posix()} if args.path else None
    report = sync_module.sync(
        _require(args.root, "--root"),
        args.manifests,
        _require(args.database, "--database"),
        options=options,
        model_cache_dir=args.model_cache_dir,
        only_relative_paths=only_paths,
    )
    report.status = cli_sync_status(report)
    not_indexed = [*report.missing_explicit_paths, *report.skipped_sources]
    if args.json:
        print(_json(dataclasses.asdict(report), indent=2))
    else:
        _print_sync_report(report)
    if not_indexed:
        print(
            f"tracecite: {len(not_indexed)} selected source(s) were not indexed: "
            f"{', '.join(not_indexed)}",
            file=sys.stderr,
        )
    return 0 if report.status == "ok" else 1


def cli_sync_status(report) -> str:
    """Return the sync status, or ``incomplete`` when a selected source was not indexed.

    The library status says whether the sync applied; the CLI also counts a
    selected source it could not index, so its status matches its exit code.
    """
    if report.status == "ok" and (
        report.missing_explicit_paths or report.skipped_sources
    ):
        return "incomplete"
    return report.status


def _print_sync_report(report) -> None:
    for heading, items in (
        ("added", report.sources_added),
        ("reparsed", report.sources_reparsed),
        ("rechunked", report.sources_rechunked),
        ("renamed", [f"{old} -> {new}" for old, new in report.sources_renamed]),
        ("selected-missing", report.selected_missing_paths),
        ("missing-sources", report.missing_explicit_paths),
        (
            "skipped",
            [f"{path}: {reason}" for path, reason in report.skipped_sources.items()],
        ),
        ("unmatched-globs", report.unmatched_globs),
        ("indexed-but-unselected", report.indexed_unselected_paths),
        ("cleanup-warnings", report.cleanup_warnings),
        (
            "pages-without-text",
            [
                f"{path}: {', '.join(map(str, pages))}"
                for path, pages in report.pages_without_text.items()
            ],
        ),
    ):
        print(f"{heading}: {len(items)}")
        for item in items:
            print(f"  {item}")
    if report.pages_without_text:
        print(
            "  scanned pages need Tesseract for OCR; if it was missing, "
            "install it and re-run sync with --full to extract their text"
        )
    print(f"unchanged: {len(report.sources_unchanged)}")
    print(
        f"chunks added={report.chunks_added} updated={report.chunks_updated} "
        f"deleted={report.chunks_deleted}"
    )
    print(f"embeddings generated: {report.embeddings_generated}")
    print(
        {
            "ok": "status: ok",
            "incomplete": "status: incomplete; the sources under missing-sources "
            "and skipped were not indexed",
            "aborted-source-changed": "status: aborted-source-changed; a source "
            "changed during sync and nothing was written, so run sync again",
        }[report.status]
    )


# Han, kana, and Hangul. The unicode61 tokenizer indexes an unspaced run of
# these characters as one token, so MATCH cannot find a word inside the run.
_CJK_RUN_RE = re.compile(
    "[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]+"
)


def _source_type_filter(source_types) -> tuple[str, list]:
    if not source_types:
        return "", []
    placeholders = ",".join("?" for _ in source_types)
    return f" AND sources.source_type IN ({placeholders})", list(source_types)


def _fts_rows(conn, query, fts_limit, source_types=None):
    rows = _match_rows(conn, query, fts_limit, source_types)
    cjk_runs = _CJK_RUN_RE.findall(query)
    if not cjk_runs or len(rows) >= fts_limit:
        return rows
    found = {row["chunk_id"] for row in rows}
    substring_rows = _cjk_substring_rows(conn, cjk_runs, fts_limit, source_types)
    return [
        *rows,
        *(row for row in substring_rows if row["chunk_id"] not in found),
    ][:fts_limit]


def _match_rows(conn, query, fts_limit, source_types):
    type_filter, type_params = _source_type_filter(source_types)
    statement = f"""
        SELECT chunks.chunk_id AS chunk_id, bm25(chunks_fts) AS score
        FROM chunks_fts
        JOIN chunks ON chunks.rowid = chunks_fts.rowid
        JOIN sources ON sources.source_pk = chunks.source_pk
        WHERE chunks_fts MATCH ?{type_filter}
        ORDER BY bm25(chunks_fts), length(sources.path), sources.path
        LIMIT ?
    """
    try:
        return conn.execute(statement, [query, *type_params, fts_limit]).fetchall()
    except sqlite3.OperationalError:
        # FTS5 reads punctuation as query syntax: `de-rating` and `heat: wind` are
        # column filters, and `?` or a lone `"` is a syntax error. Quoting each word
        # always parses; a database error fails again here and propagates.
        words = " ".join('"' + word.replace('"', '""') + '"' for word in query.split())
        rows = conn.execute(statement, [words, *type_params, fts_limit]).fetchall()
        print(
            "tracecite: the query is not valid FTS5 syntax, so lexical search "
            "matched each word instead",
            file=sys.stderr,
        )
        return rows


def _cjk_substring_rows(conn, cjk_runs, limit, source_types):
    """Find chunks whose text contains every CJK run.

    This scans every chunk's text, so it is slower than MATCH on a large
    database.
    """
    type_filter, type_params = _source_type_filter(source_types)
    contains_all = " AND ".join("instr(chunks.body, ?) > 0" for _ in cjk_runs)
    return conn.execute(
        f"""
        SELECT chunks.chunk_id AS chunk_id
        FROM chunks
        JOIN sources ON sources.source_pk = chunks.source_pk
        WHERE {contains_all}{type_filter}
        ORDER BY length(sources.path), sources.path, chunks.rowid
        LIMIT ?
        """,
        [*cjk_runs, *type_params, limit],
    ).fetchall()


def active_embedding_model(conn, model_cache_dir: Path):
    """Return the embedding model recorded as active in the database."""
    from . import sync as sync_module

    config = schema.load_config(conn)
    return sync_module.EmbeddingModel(
        config.embedding_model, config.embedding_revision, model_cache_dir
    )


def hybrid_search(
    conn, query, limit, fts_limit, vector_limit, embedder, *, source_types=None
):
    """Rank chunks by fusing lexical and vector retrieval.

    With ``embedder=None`` only lexical retrieval runs.
    """
    if not query.strip():
        raise ValueError("search query is empty")
    vector_query = query
    if embedder is not None and _CJK_RUN_RE.search(query):
        vector_query = " ".join(_CJK_RUN_RE.sub(" ", query).split())
        print(
            "tracecite: the embedding model is English-only, so "
            + (
                "vector search uses only the words without CJK text"
                if vector_query
                else "this query with CJK text uses lexical search only"
            ),
            file=sys.stderr,
        )
    fts_rows = _fts_rows(conn, query, fts_limit, source_types)
    fts_rank = {row["chunk_id"]: rank for rank, row in enumerate(fts_rows, start=1)}
    vector_rank = (
        _vector_rank(conn, vector_query, vector_limit, embedder, source_types)
        if embedder is not None and vector_query
        else {}
    )
    return _ranked_results(conn, limit, fts_rank, vector_rank)


def _vector_rank(conn, query, vector_limit, embedder, source_types) -> dict[str, int]:
    from . import vector_backend

    query_vector = embedder.embed([query])[0]

    active_model_id = schema.load_config(conn).embedding_model_id
    if source_types:
        placeholders = ",".join("?" for _ in source_types)
        allowed_rows = conn.execute(
            f"""
            SELECT DISTINCT chunk_embeddings.embedding_id
            FROM chunk_embeddings
            JOIN embeddings ON embeddings.embedding_id = chunk_embeddings.embedding_id
            JOIN chunks ON chunks.chunk_id = chunk_embeddings.chunk_id
            JOIN sources ON sources.source_pk = chunks.source_pk
            WHERE embeddings.model_id = ? AND sources.source_type IN ({placeholders})
            """,
            [active_model_id, *source_types],
        ).fetchall()
    else:
        allowed_rows = conn.execute(
            "SELECT embedding_id FROM embeddings WHERE model_id = ?", (active_model_id,)
        ).fetchall()
    allowed_ids = [row["embedding_id"] for row in allowed_rows]

    backend = vector_backend.SqliteVecBackend()
    vector_matches = backend.search(
        conn, query_vector, vector_limit, allowed_embedding_ids=allowed_ids
    )

    vector_rank: dict[str, int] = {}
    if vector_matches:
        embedding_ids = [match.embedding_id for match in vector_matches]
        placeholders = ",".join("?" for _ in embedding_ids)
        chunk_rows = conn.execute(
            f"SELECT chunk_id, embedding_id FROM chunk_embeddings WHERE embedding_id IN ({placeholders})",
            embedding_ids,
        ).fetchall()
        embedding_to_chunks: dict[int, list[str]] = defaultdict(list)
        for row in chunk_rows:
            embedding_to_chunks[row["embedding_id"]].append(row["chunk_id"])
        # Chunks with identical text share one embedding and so one rank.
        for rank, match in enumerate(vector_matches, start=1):
            for chunk_id in embedding_to_chunks.get(match.embedding_id, []):
                vector_rank.setdefault(chunk_id, rank)
    return vector_rank


def _ranked_results(conn, limit, fts_rank, vector_rank):
    fused_scores: dict[str, float] = defaultdict(float)
    provenance: dict[str, set[str]] = defaultdict(set)
    for retrieval, ranks in (("lexical", fts_rank), ("vector", vector_rank)):
        for chunk_id, rank in ranks.items():
            fused_scores[chunk_id] += 1.0 / (RRF_K + rank)
            provenance[chunk_id].add(retrieval)

    chunks = {
        row["chunk_id"]: row
        for row in conn.execute(
            "SELECT c.*, s.path AS source_path, s.source_type, s.sha256 "
            "FROM chunks c JOIN sources s USING (source_pk) "
            "WHERE c.chunk_id IN (SELECT value FROM json_each(?))",
            (json.dumps(list(fused_scores)),),
        )
    }
    # Equal scores, such as those of byte-identical files, rank the shortest
    # path first, then the first in sort order.
    ranked_chunk_ids = sorted(
        fused_scores,
        key=lambda chunk_id: (
            -fused_scores[chunk_id],
            len(chunks[chunk_id]["source_path"]),
            chunks[chunk_id]["source_path"],
        ),
    )

    results = []
    # Byte-identical files yield identical chunks; report each passage once,
    # under its best-ranked path, before applying the limit.
    by_identity: dict[tuple[str, str, str], dict] = {}
    for chunk_id in ranked_chunk_ids:
        chunk = chunks[chunk_id]
        identity = (chunk["sha256"], chunk["logical_key"], chunk["lexical_hash"])
        if identity in by_identity:
            by_identity[identity]["duplicate_paths"].append(chunk["source_path"])
            continue
        if len(results) == limit:
            continue
        entry: dict = {
            "rank": len(results) + 1,
            "source_path": chunk["source_path"],
            "source_type": chunk["source_type"],
            "source_sha256": chunk["sha256"],
            "heading_path": json.loads(chunk["heading_path"])
            if chunk["heading_path"]
            else [],
            "passage": chunk["body"],
            "physical_page": chunk["physical_page"],
            "page_offsets": {
                "start": chunk["page_start_offset"],
                "end": chunk["page_end_offset"],
            },
            "page_range": {
                "start": chunk["page_range_start"],
                "end": chunk["page_range_end"],
            },
            "line_range": {"start": chunk["line_start"], "end": chunk["line_end"]},
            "locator": json.loads(chunk["locator_json"])
            if chunk["locator_json"]
            else {},
            "content_type": chunk["content_type"],
            "provenance": sorted(provenance[chunk_id]),
            "fused_score": fused_scores[chunk_id],
            "duplicate_paths": [],
        }
        if chunk["source_type"] == "pdf" and chunk["physical_page"] is not None:
            entry["pdf_link"] = f"{chunk['source_path']}#page={chunk['physical_page']}"
        by_identity[identity] = entry
        results.append(entry)
    for entry in results:
        entry["duplicate_paths"].sort()
    return results


def cmd_search(args: argparse.Namespace) -> int:
    from .page_output import page_assets_for

    with _database(args.database) as conn:
        model_cache_dir = (
            args.model_cache_dir or Path(args.database).resolve().parent / "model-cache"
        )
        results = hybrid_search(
            conn,
            args.query,
            args.limit,
            args.fts_limit,
            args.vector_limit,
            None
            if args.lexical_only
            else active_embedding_model(conn, model_cache_dir),
            source_types=args.source_types,
        )
        source_pks = {
            row["path"]: row["source_pk"]
            for row in conn.execute("SELECT path, source_pk FROM sources")
        }
        for result in results:
            page = result["physical_page"]
            result["page_render"], result["figure_crops"] = (
                page_assets_for(
                    conn, args.database, source_pks[result["source_path"]], page
                )
                if page is not None
                else (None, [])
            )
        print(_json(results, indent=2))
    return 0


def cmd_page(args: argparse.Namespace) -> int:
    from .page_output import page_json_payload
    from .page_selection import (
        PageSelectionSyntaxError,
        PageSelectionUnavailableError,
        resolve_page_selection,
    )

    with _database(args.database) as conn:
        source_path, source_row = _indexed_source(conn, args)
        if source_row is None:
            print(f"not-found: {source_path} page {args.page or 1}", file=sys.stderr)
            return 1
        if source_row["source_type"] == "workbook":
            print(f"source is not a pdf: {source_path}", file=sys.stderr)
            return 2
        rows = conn.execute(
            "SELECT * FROM pages WHERE source_pk = ? ORDER BY physical_page",
            (source_row["source_pk"],),
        ).fetchall()
        available_pages = [row["physical_page"] for row in rows]
        try:
            selected_pages = resolve_page_selection(args.page, available_pages)
        except PageSelectionSyntaxError as exc:
            print(f"tracecite: {exc}", file=sys.stderr)
            return 2
        except PageSelectionUnavailableError as exc:
            print(f"not-found: {source_path} page {exc.page}", file=sys.stderr)
            return 1
        selected_rows = {
            row["physical_page"]: row
            for row in rows
            if row["physical_page"] in selected_pages
        }
        for page in selected_pages:
            if not selected_rows[page]["text"].strip():
                print(
                    f"note: physical page {page} of {source_path} has no extracted "
                    "text; a scanned page needs OCR (Tesseract) during sync",
                    file=sys.stderr,
                )
        if args.format == "json":
            payload = [
                page_json_payload(conn, args.database, source_row, selected_rows[page])
                for page in selected_pages
            ]
            print(_json(payload, indent=2))
        elif len(selected_pages) == 1:
            print(selected_rows[selected_pages[0]]["text"])
        else:
            for index, page in enumerate(selected_pages):
                if index:
                    print()
                print(f"--- physical page {page} ---")
                print(selected_rows[page]["text"])
    return 0


def cmd_extract_pages(args: argparse.Namespace) -> int:
    from .page_extraction import extract_pages

    with _database(args.database) as conn:
        root = Path(args.root or Path.cwd()).resolve()
        result = extract_pages(conn, root, args.source_path, args.page, args.output_dir)
        print(
            _json(
                {
                    "pdf_path": str(result.pdf_path),
                    "manifest_path": str(result.manifest_path),
                    "normalized_pages": result.normalized_pages,
                },
                indent=2,
            )
        )
    return 0


def cmd_verify_quote(args: argparse.Namespace) -> int:
    from . import verify

    page_range = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", args.page)
    first, last = (
        (int(page_range[1]), int(page_range[2] or page_range[1]))
        if page_range
        else (0, 0)
    )
    if not 1 <= first <= last:
        print(
            f"tracecite: verify quote takes a page or a page range such as 4-5: {args.page}",
            file=sys.stderr,
        )
        return 2
    with _database(args.database) as conn:
        source_path, source_row = _indexed_source(conn, args)
        if source_row is None:
            print(f"tracecite: {source_path} is not indexed", file=sys.stderr)
            result = verify.QuoteVerification(
                "source-not-indexed", first, args.quote, source_path=source_path
            )
        else:
            result = verify.verify_quote(conn, source_path, first, args.quote, last)
            if result.status == "page-not-indexed":
                (page_count,) = conn.execute(
                    "SELECT count(*) FROM pages WHERE source_pk = ?",
                    (source_row["source_pk"],),
                ).fetchone()
                print(
                    f"tracecite: {source_path} has {page_count} indexed page(s), "
                    f"so page {args.page.strip()} is out of range",
                    file=sys.stderr,
                )
        print(_json({**_quote_json(result), "last_page": last}))
    if result.status in {"exact", "normalised"}:
        return 0
    return 2 if result.status.endswith("-not-indexed") else 1


def _quote_json(result) -> dict:
    return {
        "status": result.status,
        "page": result.physical_page,
        "quote": result.quote,
        "citation_key": result.citation_key,
        "source_path": result.source_path,
    }


def cmd_verify_report(args: argparse.Namespace) -> int:
    from . import verify

    with _database(args.database) as conn:
        result = verify.verify_report(
            conn,
            args.report_path,
            args.root or Path.cwd(),
            source_links_path=args.source_links,
            source_links_root=args.source_links_root,
        )
        print(
            _json(
                {
                    "citation_issues": [
                        issue.__dict__ for issue in result.citation_issues
                    ],
                    "quote_results": [_quote_json(q) for q in result.quote_results],
                    "source_link_issues": result.source_link_issues,
                    "ok": result.ok,
                },
                indent=2,
            )
        )
    return 0 if result.ok else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    from . import sync as sync_module

    with _database(args.database) as conn:
        issues = sync_module.integrity_check(conn)
        for issue in issues:
            print(f"ISSUE: {issue}")
        warnings = _print_warnings(conn, args.root)
        if not issues:
            print(f"doctor: no integrity issues found, {warnings} warning(s)")
        return 0 if not issues else 1


def _print_warnings(conn, root: Path | None) -> int:
    """Print and count the warnings: PDF pages without text and, with a root,
    indexed sources whose files changed or disappeared.

    These are not integrity issues: the indexed text stays citable.
    """
    from .paths import source_file_state

    warnings = 0
    blank_pages: dict[str, list[str]] = defaultdict(list)
    for path, page in conn.execute(
        "SELECT path, physical_page FROM pages JOIN sources USING (source_pk) "
        "WHERE source_type = 'pdf' AND trim(text, char(9, 10, 13, 32)) = '' "
        "ORDER BY path, physical_page"
    ):
        blank_pages[path].append(str(page))
    if blank_pages:
        warnings += 1
        print(
            f"WARNING: {sum(map(len, blank_pages.values()))} PDF page(s) have no "
            "extracted text; scanned pages need Tesseract, then tracecite sync --full:"
        )
        for path, pages in blank_pages.items():
            print(f"  {path}: {', '.join(pages)}")
    if root is None:
        return warnings
    states: dict[str, list[str]] = defaultdict(list)
    for row in conn.execute("SELECT * FROM sources ORDER BY path"):
        states[source_file_state(Path(root), row)].append(row["path"])
    for state, message in (
        (
            "changed",
            (
                "changed on disk since sync; run tracecite sync, which lists any "
                "file it cannot parse under skipped"
            ),
        ),
        ("missing", "missing under the root"),
    ):
        if states[state]:
            warnings += 1
            print(f"WARNING: {len(states[state])} indexed source(s) {message}:")
            for path in states[state]:
                print(f"  {path}")
    return warnings


def cmd_prune(args: argparse.Namespace) -> int:
    from . import manifest as manifest_module
    from . import sync as sync_module

    rules = sync_module.load_manifest_rules(args.manifests)
    prune_all = args.prune_all
    selects_any = bool(rules.explicit_paths or rules.include_globs)
    if prune_all and (selects_any or rules.exclude_globs):
        print(
            "prune --all cannot be combined with source/include/exclude rules",
            file=sys.stderr,
        )
        return 2
    if not prune_all and not selects_any:
        print(
            "prune requires at least one positive source/include rule; excludes only refine it",
            file=sys.stderr,
        )
        return 2
    # A missing root would make every selected source look deleted.
    if not prune_all and (args.root is None or not Path(args.root).is_dir()):
        print(
            "prune requires --root (or a profile root) to be an existing directory, "
            f"got {args.root}; use --all to prune every source",
            file=sys.stderr,
        )
        return 2
    with _database(args.database) as conn:
        selected = set()
        missing: list[str] = []
        if not prune_all:
            matched = {
                row["path"]
                for row in conn.execute("SELECT path FROM sources").fetchall()
                if rules.selects_path(row["path"])
            }
            if not matched:
                print(
                    "prune selection matched zero indexed sources; use --all explicitly to prune every source",
                    file=sys.stderr,
                )
                return 2
            present = manifest_module.resolve_sources(Path(args.root), rules).selected
            selected = matched & present.keys()
            missing = sorted(matched - selected)
        plan = sync_module.plan_prune(conn, selected)
        sync_module.validate_prune_plan(conn, args.database, plan)
    leaks = []
    if args.apply:
        with _database(args.database, read_only=False) as conn:
            leaks = sync_module.apply_prune(conn, args.database, plan)
    status = "preview"
    if args.apply:
        status = "applied-with-cleanup-warnings" if leaks else "applied"
    print(
        _json(
            {
                "status": status,
                "selected_count": len(selected),
                "planned_count": len(plan),
                "paths": list(plan),
                "missing_paths": missing,
                "applied": bool(args.apply),
                "database_committed": bool(args.apply),
                "cleanup_warnings": leaks,
            }
        )
    )
    return 3 if args.apply and leaks else 0


def dispatch(handler, args: argparse.Namespace) -> int:
    args = _resolve_runtime_args(args)
    try:
        return handler(args)
    except sqlite3.DatabaseError as exc:
        # A damaged page can pass the open-time check and fail mid-query.
        print(f"tracecite: database error in {args.database}: {exc}", file=sys.stderr)
        return 2
    except PathAuthorityError as exc:
        print(_json({"error": "path-error", "detail": str(exc)}), file=sys.stderr)
        return 2
    except (PageOutputError, PageExtractionError) as exc:
        print(exc, file=sys.stderr)
        return exc.exit_code
