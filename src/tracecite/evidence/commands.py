from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
import sys

from . import config as config_module

RRF_K = 60


def _require(value, flag: str):
    if value is None:
        raise SystemExit(f"error: {flag} is required for this command")
    return value


def _connect_existing_or_report(schema_module, database: Path, *, read_only: bool):
    try:
        return schema_module.connect_existing(_require(database, "--database"), read_only=read_only)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return None


def _rules_have_selection(rules) -> bool:
    return bool(rules.explicit_paths or rules.include_globs)


def _resolve_runtime_args(args: argparse.Namespace) -> argparse.Namespace:
    profile_path = config_module.discover_profile(Path.cwd(), getattr(args, "config", None))
    profile = config_module.load_profile(profile_path) if profile_path is not None else None
    if getattr(args, "root", None) is None and profile is not None:
        args.root = profile.root
    if getattr(args, "database", None) is None and profile is not None:
        args.database = profile.database
    if getattr(args, "model_cache_dir", None) is None and profile is not None:
        args.model_cache_dir = profile.model_cache_dir
    if profile is not None:
        explicit_manifests = list(getattr(args, "manifests", None) or [])
        args.manifests = list(profile.manifests) + explicit_manifests
    return args


def cmd_sync(args: argparse.Namespace) -> int:
    from . import sync as sync_module

    options = sync_module.SyncOptions(
        max_chunk_chars=args.max_chunk_chars,
        generate_assets=not args.no_assets,
        full=args.full,
        reembed=args.reembed,
        ocr_lang=args.ocr_lang,
    )
    only_paths = {Path(args.path).as_posix()} if args.path else None
    manifests = getattr(args, "manifests", None) or []
    report = sync_module.sync(
        _require(getattr(args, "root", None), "--root"),
        manifests,
        _require(args.database, "--database"),
        options=options,
        model_cache_dir=args.model_cache_dir,
        only_relative_paths=only_paths,
    )
    print(f"status: {report.status}")
    print(f"added: {report.sources_added}")
    print(f"reparsed: {report.sources_reparsed}")
    print(f"rechunked: {report.sources_rechunked}")
    print(f"renamed: {report.sources_renamed}")
    print(f"selected-missing: {report.selected_missing_paths}")
    print(f"unmatched-globs: {report.unmatched_globs}")
    print(f"indexed-but-unselected: {getattr(report, 'indexed_unselected_paths', [])}")
    print(f"cleanup-warnings: {report.cleanup_warnings}")
    print(f"unchanged: {len(report.sources_unchanged)} source(s)")
    print(
        f"chunks added={report.chunks_added} updated={report.chunks_updated} "
        f"deleted={report.chunks_deleted}"
    )
    print(f"embeddings generated: {report.embeddings_generated}")
    return 0 if report.status == "ok" else 1


def _relative_pdf_link(database_path: Path, sources_dir: Path | None, source_row, page: int) -> str:
    path = source_row["path"]
    return f"{path}#page={page}"


def _fts_rows(conn, query, fts_limit):
    statement = """
        SELECT chunks.chunk_id AS chunk_id, bm25(chunks_fts) AS score
        FROM chunks_fts
        JOIN chunks ON chunks.rowid = chunks_fts.rowid
        WHERE chunks_fts MATCH ?
        ORDER BY bm25(chunks_fts)
        LIMIT ?
    """
    try:
        return conn.execute(statement, (query, fts_limit)).fetchall()
    except sqlite3.OperationalError as exc:
        if not str(exc).startswith("fts5: syntax error"):
            raise
        fallback_query = f'"{query.replace(chr(34), chr(34) * 2)}"'
        print(
            "FTS5 lexical search rejected the query syntax; using a quoted lexical fallback. "
            "Vector retrieval still uses the original query.",
            file=sys.stderr,
        )
        return conn.execute(statement, (fallback_query, fts_limit)).fetchall()


def _search(conn, sources_dir, query, limit, fts_limit, vector_limit, model_cache_dir, database_path):
    from . import schema, sync as sync_module, vector_backend

    config = schema.load_config(conn)

    fts_rows = _fts_rows(conn, query, fts_limit)
    fts_rank = {row["chunk_id"]: rank for rank, row in enumerate(fts_rows, start=1)}

    if hasattr(model_cache_dir, "embed"):
        embedder = model_cache_dir
    else:
        embedder = sync_module.EmbeddingModel(
            config.embedding_model,
            config.embedding_revision,
            model_cache_dir or (Path(database_path).resolve().parent / "model-cache"),
        )
    query_vector = embedder.embed([query])[0]

    active_model_id = config.embedding_model_id
    allowed_rows = conn.execute(
        "SELECT embedding_id FROM embeddings WHERE model_id = ?", (active_model_id,)
    ).fetchall()
    allowed_ids = [row["embedding_id"] for row in allowed_rows]

    backend = vector_backend.SqliteVecBackend()
    vector_matches = backend.search(conn, query_vector, vector_limit, allowed_embedding_ids=allowed_ids)

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

    fused_scores: dict[str, float] = defaultdict(float)
    provenance: dict[str, set[str]] = defaultdict(set)
    for chunk_id, rank in fts_rank.items():
        fused_scores[chunk_id] += 1.0 / (RRF_K + rank)
        provenance[chunk_id].add("lexical")
    for chunk_id, rank in vector_rank.items():
        fused_scores[chunk_id] += 1.0 / (RRF_K + rank)
        provenance[chunk_id].add("vector")

    ranked_chunk_ids = sorted(fused_scores, key=lambda cid: fused_scores[cid], reverse=True)[:limit]

    results = []
    for position, chunk_id in enumerate(ranked_chunk_ids, start=1):
        chunk = conn.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        if chunk is None:
            continue
        source_row = conn.execute(
            "SELECT * FROM sources WHERE source_pk = ?", (chunk["source_pk"],)
        ).fetchone()
        entry = {
            "rank": position,
            "source_path": source_row["path"] if source_row else None,
            "heading_path": json.loads(chunk["heading_path"]) if chunk["heading_path"] else [],
            "passage": chunk["body"],
            "physical_page": chunk["physical_page"],
            "page_offsets": {"start": chunk["page_start_offset"], "end": chunk["page_end_offset"]},
            "page_range": {"start": chunk["page_range_start"], "end": chunk["page_range_end"]},
            "line_range": {"start": chunk["line_start"], "end": chunk["line_end"]},
            "content_type": chunk["content_type"],
            "provenance": sorted(provenance[chunk_id]),
            "fused_score": fused_scores[chunk_id],
        }
        if source_row is not None and chunk["physical_page"] is not None:
            entry["pdf_link"] = _relative_pdf_link(
                database_path, sources_dir, source_row, chunk["physical_page"]
            )
        results.append(entry)
    return results


def hybrid_search(
    conn,
    sources_dir,
    query,
    limit,
    fts_limit,
    vector_limit,
    model_cache_dir,
    database_path,
    *,
    embedder=None,
):
    return _search(
        conn,
        sources_dir,
        query,
        limit,
        fts_limit,
        vector_limit,
        embedder if embedder is not None else model_cache_dir,
        database_path,
    )


def cmd_search(args: argparse.Namespace) -> int:
    from . import schema

    conn = _connect_existing_or_report(schema, args.database, read_only=True)
    if conn is None:
        return 2
    try:
        schema.ensure_schema(conn)
        results = _search(
            conn,
            getattr(args, "root", None),
            args.query,
            args.limit,
            args.fts_limit,
            args.vector_limit,
            args.model_cache_dir,
            args.database,
        )
        print(json.dumps(results, indent=2))
    finally:
        conn.close()
    return 0


def cmd_page(args: argparse.Namespace) -> int:
    from . import schema
    from .paths import PathAuthorityError, normalise_source_path, source_row_for_path

    conn = _connect_existing_or_report(schema, args.database, read_only=True)
    if conn is None:
        return 2
    try:
        schema.ensure_schema(conn)
        root = Path(getattr(args, "root", None) or Path.cwd()).resolve()
        try:
            source_path = normalise_source_path(root, args.source_path)
        except PathAuthorityError as exc:
            print(json.dumps({"error": "path-error", "detail": str(exc)}), file=sys.stderr)
            return 2
        source_row = source_row_for_path(conn, source_path)
        if source_row is None:
            print(f"not-found: {source_path} page {args.page}", file=sys.stderr)
            return 1
        row = conn.execute(
            "SELECT pages.* FROM pages WHERE source_pk = ? AND physical_page = ?",
            (source_row["source_pk"], args.page),
        ).fetchone()
        if row is None:
            print(f"not-found: {source_path} page {args.page}", file=sys.stderr)
            return 1
        print(row["text"])
    finally:
        conn.close()
    return 0


def cmd_verify_quote(args: argparse.Namespace) -> int:
    from . import schema, verify
    from .paths import PathAuthorityError, normalise_source_path, source_row_for_path

    conn = _connect_existing_or_report(schema, args.database, read_only=True)
    if conn is None:
        return 2
    try:
        schema.ensure_schema(conn)
        root = Path(getattr(args, "root", None) or Path.cwd()).resolve()
        try:
            source_path = normalise_source_path(root, args.source_path)
        except PathAuthorityError as exc:
            print(json.dumps({"error": "path-error", "detail": str(exc)}), file=sys.stderr)
            return 2
        if source_row_for_path(conn, source_path) is None:
            result = verify.QuoteVerification("not-found", args.page, args.quote)
        else:
            result = verify.verify_quote(conn, source_path, args.page, args.quote)
        print(
            json.dumps(
                {
                    "status": result.status,
                    "page": result.physical_page,
                    "quote": result.quote,
                    "citation_key": result.citation_key,
                    "source_path": result.source_path,
                }
            )
        )
    finally:
        conn.close()
    return 0 if result.status in {"exact", "normalised"} else 1


def cmd_verify_report(args: argparse.Namespace) -> int:
    from . import schema, verify

    conn = _connect_existing_or_report(schema, args.database, read_only=True)
    if conn is None:
        return 2
    try:
        schema.ensure_schema(conn)
        result = verify.verify_report(
            conn, args.report_path, args.root or Path.cwd(), source_links_path=args.source_links, source_links_root=args.source_links_root
        )
        print(
            json.dumps(
                {
                    "citation_issues": [issue.__dict__ for issue in result.citation_issues],
                    "quote_results": [
                        {
                            "status": q.status,
                            "page": q.physical_page,
                            "quote": q.quote,
                            "citation_key": q.citation_key,
                            "source_path": q.source_path,
                        }
                        for q in result.quote_results
                    ],
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
    from . import schema, sync as sync_module

    conn = _connect_existing_or_report(schema, args.database, read_only=True)
    if conn is None:
        return 2
    try:
        schema.ensure_schema(conn)
        issues = sync_module.integrity_check(conn)
        for issue in issues:
            print(f"ISSUE: {issue}")
        if not issues:
            print("doctor: no issues found")
        return 0 if not issues else 1
    finally:
        conn.close()


def cmd_prune(args: argparse.Namespace) -> int:
    from . import schema, sync as sync_module

    rules = sync_module.load_manifest_rules(getattr(args, "manifests", None) or [])
    prune_all = bool(getattr(args, "prune_all", False))
    has_any_rules = bool(rules.explicit_paths or rules.include_globs or rules.exclude_globs)
    if prune_all and has_any_rules:
        print("prune --all cannot be combined with source/include/exclude rules", file=sys.stderr)
        return 2
    if not prune_all and not _rules_have_selection(rules):
        print("prune requires at least one positive source/include rule; excludes only refine it", file=sys.stderr)
        return 2
    conn = _connect_existing_or_report(schema, args.database, read_only=True)
    if conn is None:
        return 2
    try:
        schema.ensure_schema(conn)
        selected = set()
        if not prune_all:
            selected = {
                row["path"]
                for row in conn.execute("SELECT path FROM sources").fetchall()
                if rules.selects_path(row["path"])
            }
            if not selected:
                print(
                    "prune selection matched zero indexed sources; use --all explicitly to prune every source",
                    file=sys.stderr,
                )
                return 2
        plan = sync_module.plan_prune(conn, selected)
        sync_module.validate_prune_plan(conn, args.database, plan)
        leaks = []
        if args.apply:
            conn.close()
            conn = _connect_existing_or_report(schema, args.database, read_only=False)
            if conn is None:
                return 2
            schema.ensure_schema(conn)
            leaks = sync_module.apply_prune(conn, args.database, plan)
        status = "preview"
        if args.apply:
            status = "applied-with-cleanup-warnings" if leaks else "applied"
        print(
            json.dumps(
                {
                    "status": status,
                    "selected_count": len(selected),
                    "planned_count": len(plan.paths),
                    "paths": list(plan.paths),
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
        return {"quote": cmd_verify_quote, "report": cmd_verify_report}[args.verify_command](args)
    handlers = {"sync": cmd_sync, "search": cmd_search, "page": cmd_page, "prune": cmd_prune, "doctor": cmd_doctor}
    return handlers[args.command](args)
