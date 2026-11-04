from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from . import config as config_module
from . import schema

RRF_K = 60


def _json(value, indent: int | None = None) -> str:
    return json.dumps(value, indent=indent, ensure_ascii=False)


def _require(value, flag: str):
    if value is None:
        raise SystemExit(f"error: {flag} is required for this command")
    return value


def _connect(database: Path, *, read_only: bool):
    try:
        return schema.connect_existing(
            _require(database, "--database"), read_only=read_only
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return None


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
        max_chunk_chars=args.max_chunk_chars,
        generate_assets=not args.no_assets,
        full=args.full,
        reembed=args.reembed,
    )
    only_paths = {Path(args.path).as_posix()} if args.path else None
    report = sync_module.sync(
        _require(args.root, "--root"),
        args.manifests,
        _require(args.database, "--database"),
        options=options,
        model_cache_dir=args.model_cache_dir,
        only_relative_paths=only_paths,
    )
    if args.json:
        print(_json(dataclasses.asdict(report), indent=2))
    else:
        _print_sync_report(report)
    if report.missing_explicit_paths:
        print(
            f"tracecite: {len(report.missing_explicit_paths)} declared [[source]] "
            f"path(s) do not exist under the root: "
            f"{', '.join(report.missing_explicit_paths)}",
            file=sys.stderr,
        )
        return 1
    return 0 if report.status == "ok" else 1


def _print_sync_report(report) -> None:
    print(f"status: {report.status}")
    for heading, items in (
        ("added", report.sources_added),
        ("reparsed", report.sources_reparsed),
        ("rechunked", report.sources_rechunked),
        ("renamed", [f"{old} -> {new}" for old, new in report.sources_renamed]),
        ("selected-missing", report.selected_missing_paths),
        ("missing-sources", report.missing_explicit_paths),
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
    if report.ocr_unavailable:
        print(
            "OCR was unavailable, so scanned pages were stored without text; "
            "install Tesseract and re-run sync with --full to extract it"
        )
    print(f"unchanged: {len(report.sources_unchanged)}")
    print(
        f"chunks added={report.chunks_added} updated={report.chunks_updated} "
        f"deleted={report.chunks_deleted}"
    )
    print(f"embeddings generated: {report.embeddings_generated}")


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
        ORDER BY bm25(chunks_fts)
        LIMIT ?
    """
    try:
        return conn.execute(statement, [query, *type_params, fts_limit]).fetchall()
    except sqlite3.OperationalError as exc:
        if not str(exc).startswith("fts5: syntax error"):
            raise
        fallback_query = f'"{query.replace(chr(34), chr(34) * 2)}"'
        print(
            "FTS5 lexical search rejected the query syntax; using a quoted lexical fallback. "
            "Vector retrieval still uses the original query.",
            file=sys.stderr,
        )
        return conn.execute(
            statement, [fallback_query, *type_params, fts_limit]
        ).fetchall()


def _cjk_substring_rows(conn, cjk_runs, limit, source_types):
    """Find chunks whose text contains every CJK run, most occurrences first.

    This scans every chunk's text, so it is slower than MATCH on a large
    database.
    """
    type_filter, type_params = _source_type_filter(source_types)
    occurrences = " + ".join(
        "(length(chunks.body) - length(replace(chunks.body, ?, ''))) / length(?)"
        for _ in cjk_runs
    )
    contains_all = " AND ".join("instr(chunks.body, ?) > 0" for _ in cjk_runs)
    return conn.execute(
        f"""
        SELECT chunks.chunk_id AS chunk_id, {occurrences} AS score
        FROM chunks
        JOIN sources ON sources.source_pk = chunks.source_pk
        WHERE {contains_all}{type_filter}
        ORDER BY score DESC, chunks.rowid
        LIMIT ?
        """,
        [
            *(run for run in cjk_runs for _ in range(2)),
            *cjk_runs,
            *type_params,
            limit,
        ],
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
    fts_rows = _fts_rows(conn, query, fts_limit, source_types)
    fts_rank = {row["chunk_id"]: rank for rank, row in enumerate(fts_rows, start=1)}
    vector_rank = (
        {}
        if embedder is None
        else _vector_rank(conn, query, vector_limit, embedder, source_types)
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
        rank = 0
        for match in vector_matches:
            for chunk_id in embedding_to_chunks.get(match.embedding_id, []):
                rank += 1
                vector_rank.setdefault(chunk_id, rank)
    return vector_rank


def _ranked_results(conn, limit, fts_rank, vector_rank):
    fused_scores: dict[str, float] = defaultdict(float)
    provenance: dict[str, set[str]] = defaultdict(set)
    for retrieval, ranks in (("lexical", fts_rank), ("vector", vector_rank)):
        for chunk_id, rank in ranks.items():
            fused_scores[chunk_id] += 1.0 / (RRF_K + rank)
            provenance[chunk_id].add(retrieval)

    ranked_chunk_ids = sorted(fused_scores, key=fused_scores.get, reverse=True)

    results = []
    # Byte-identical files yield identical chunks; report each passage once,
    # under its best-ranked path, before applying the limit.
    by_identity: dict[tuple[str, str, str], dict] = {}
    for chunk_id in ranked_chunk_ids:
        chunk = conn.execute(
            "SELECT c.*, s.path AS source_path, s.source_type, s.sha256 "
            "FROM chunks c JOIN sources s USING (source_pk) WHERE c.chunk_id = ?",
            (chunk_id,),
        ).fetchone()
        identity = (chunk["sha256"], chunk["logical_key"], chunk["lexical_hash"])
        if identity in by_identity:
            by_identity[identity]["duplicate_paths"].append(chunk["source_path"])
            continue
        if len(results) == limit:
            continue
        entry = {
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
    from .page_output import PageAssetMissingError, PageOutputError, page_assets_for

    conn = _connect(args.database, read_only=True)
    if conn is None:
        return 2
    try:
        schema.ensure_schema(conn)
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
    except PageAssetMissingError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except PageOutputError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        conn.close()
    return 0


def cmd_page(args: argparse.Namespace) -> int:
    from .page_output import PageAssetMissingError, PageOutputError, page_json_payload
    from .page_selection import (
        PageSelectionSyntaxError,
        PageSelectionUnavailableError,
        resolve_page_selection,
    )
    from .paths import PathAuthorityError, normalise_source_path, source_row_for_path

    conn = _connect(args.database, read_only=True)
    if conn is None:
        return 2
    try:
        schema.ensure_schema(conn)
        root = Path(args.root or Path.cwd()).resolve()
        try:
            source_path = normalise_source_path(root, args.source_path)
        except PathAuthorityError as exc:
            print(_json({"error": "path-error", "detail": str(exc)}), file=sys.stderr)
            return 2
        source_row = source_row_for_path(conn, source_path)
        if source_row is None:
            print(f"not-found: {source_path} page 1", file=sys.stderr)
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
            try:
                payload = [
                    page_json_payload(
                        conn, args.database, source_row, selected_rows[page]
                    )
                    for page in selected_pages
                ]
            except PageAssetMissingError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except PageOutputError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            print(_json(payload, indent=2))
        elif len(selected_pages) == 1:
            print(selected_rows[selected_pages[0]]["text"])
        else:
            for index, page in enumerate(selected_pages):
                if index:
                    print()
                print(f"--- physical page {page} ---")
                print(selected_rows[page]["text"])
    finally:
        conn.close()
    return 0


def cmd_extract_pages(args: argparse.Namespace) -> int:
    from .page_extraction import (
        PageExtractionError,
        PageExtractionMissingError,
        extract_pages,
    )

    conn = _connect(args.database, read_only=True)
    if conn is None:
        return 2
    try:
        schema.ensure_schema(conn)
        root = Path(args.root or Path.cwd()).resolve()
        try:
            result = extract_pages(
                conn, root, args.source_path, args.page, args.output_dir
            )
        except PageExtractionMissingError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except PageExtractionError as exc:
            print(str(exc), file=sys.stderr)
            return 2
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
    finally:
        conn.close()
    return 0


def cmd_verify_quote(args: argparse.Namespace) -> int:
    from . import verify
    from .paths import (
        PathAuthorityError,
        normalise_source_path,
        source_file_state,
        source_row_for_path,
    )

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
    pages = list(range(first, last + 1))
    conn = _connect(args.database, read_only=True)
    if conn is None:
        return 2
    try:
        schema.ensure_schema(conn)
        root = Path(args.root or Path.cwd()).resolve()
        try:
            source_path = normalise_source_path(root, args.source_path)
        except PathAuthorityError as exc:
            print(_json({"error": "path-error", "detail": str(exc)}), file=sys.stderr)
            return 2
        source_row = source_row_for_path(conn, source_path)
        source_state = None
        if source_row is None:
            result = verify.QuoteVerification("not-found", first, args.quote)
        else:
            source_state = source_file_state(root, source_row)
            if source_state == "changed":
                print(
                    f"warning: {source_row['path']} changed on disk since it was "
                    "indexed; this check used the indexed text, so re-run "
                    "tracecite sync to verify against the current file",
                    file=sys.stderr,
                )
            result = verify.verify_quote_pages(conn, source_path, pages, args.quote)
        print(
            _json({**_quote_json(result), "pages": pages, "source_state": source_state})
        )
    finally:
        conn.close()
    return 0 if result.status in {"exact", "normalised"} else 1


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

    conn = _connect(args.database, read_only=True)
    if conn is None:
        return 2
    try:
        schema.ensure_schema(conn)
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
    finally:
        conn.close()
    return 0 if result.ok else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    from . import sync as sync_module

    conn = _connect(args.database, read_only=True)
    if conn is None:
        return 2
    try:
        schema.ensure_schema(conn)
        issues = sync_module.integrity_check(conn)
        for issue in issues:
            print(f"ISSUE: {issue}")
        if args.root is not None:
            _print_source_state_warnings(conn, Path(args.root))
        if not issues:
            print("doctor: no issues found")
        return 0 if not issues else 1
    finally:
        conn.close()


def _print_source_state_warnings(conn, root: Path) -> None:
    """Report indexed sources whose files differ from the indexed version.

    These are warnings, not integrity issues: the indexed text stays
    citable after its file changes or disappears.
    """
    from .paths import source_file_state

    states: dict[str, list[str]] = defaultdict(list)
    for row in conn.execute("SELECT * FROM sources ORDER BY path"):
        states[source_file_state(root, row)].append(row["path"])
    for state, message in (
        ("changed", "changed on disk since sync; re-run tracecite sync"),
        ("missing", "missing under the root"),
    ):
        if states[state]:
            print(f"WARNING: {len(states[state])} indexed source(s) {message}:")
            for path in states[state]:
                print(f"  {path}")


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
    if not prune_all and args.root is None:
        print(
            "prune requires --root (or a profile root) to find selected sources "
            "whose files no longer exist; use --all to prune every source",
            file=sys.stderr,
        )
        return 2
    # A missing root would make every selected source look deleted.
    if not prune_all and not Path(args.root).is_dir():
        print(f"prune root is not a directory: {args.root}", file=sys.stderr)
        return 2
    conn = _connect(args.database, read_only=True)
    if conn is None:
        return 2
    try:
        schema.ensure_schema(conn)
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
            conn.close()
            conn = _connect(args.database, read_only=False)
            if conn is None:
                return 2
            schema.ensure_schema(conn)
            leaks = sync_module.apply_prune(conn, args.database, plan)
        status = "preview"
        if args.apply:
            status = "applied-with-cleanup-warnings" if leaks else "applied"
        print(
            _json(
                {
                    "status": status,
                    "selected_count": len(selected),
                    "planned_count": len(plan.paths),
                    "paths": list(plan.paths),
                    "missing_paths": missing,
                    "applied": bool(args.apply),
                    "database_committed": bool(args.apply),
                    "cleanup_warnings": leaks,
                }
            )
        )
        return 3 if args.apply and leaks else 0
    finally:
        if conn is not None:
            conn.close()


def dispatch(args: argparse.Namespace) -> int:
    args = _resolve_runtime_args(args)
    if args.command == "verify":
        handler = {"quote": cmd_verify_quote, "report": cmd_verify_report}[
            args.verify_command
        ]
    else:
        handler = {
            "sync": cmd_sync,
            "search": cmd_search,
            "page": cmd_page,
            "extract-pages": cmd_extract_pages,
            "prune": cmd_prune,
            "doctor": cmd_doctor,
        }[args.command]
    try:
        return handler(args)
    except sqlite3.DatabaseError as exc:
        # A damaged page can pass the open-time check and fail mid-query.
        print(f"tracecite: database error in {args.database}: {exc}", file=sys.stderr)
        return 2
