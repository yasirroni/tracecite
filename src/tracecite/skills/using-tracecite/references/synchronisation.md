# Synchronisation Lifecycle

```text
scan configured paths (explicit manifest entries plus include/exclude globs under --root)
    |
hash each selected source through a stable non-symlink file descriptor
    |
copy every add/reparse source into an immutable per-sync parsing snapshot
    |
parse only genuinely changed or invalidated sources
    |
diff old vs new chunks (three-pass matching)
    |
look up embedding cache, generate only missing embeddings (before any write)
    |
one BEGIN IMMEDIATE ... COMMIT transaction that rechecks source state before COMMIT (skipped entirely if there is nothing to do)
```

`sync.sync()` returns a `SyncReport` (added/reparsed/rechunked/renamed/unchanged source lists,
selected sources whose files are missing, indexed sources the manifest no longer selects, skipped
sources with their reason, chunk add/update/delete counts, `embeddings_generated`, and a `status`
field: `"ok"` or `"aborted-source-changed"`).

`sync` never deletes a source. A source whose file is gone, or that the manifest no longer selects,
keeps its rows and is listed in `selected_missing_paths` or `indexed_unselected_paths` until
`prune --apply` removes it.

## Invalidation rules

| Change | Required work |
|---|---|
| File SHA-256 changed | Reparse and rechunk that source |
| Parser metadata changed (even with byte-identical file) | Reparse and rechunk that source |
| Chunker metadata changed only | Rechunk from `pages.layout_json`; the source file is never reopened |
| Normalisation metadata changed | Renormalise/rechunk; only chunks whose semantic hash actually changed get re-embedded |
| Embedding model, revision, or dimensions changed | Not done in place. The change bumps the schema version, and `ensure_schema()` rejects a database with an older version, so the database is rebuilt at a fresh path |
| Path-only rename or manifest path change with matching content | Update the normalised `path` and locator hints while preserving the internal source key when the match is unambiguous |
| Unambiguous same-hash path replacement | Preserve chunks/embeddings where possible; public evidence identity remains the normalised path plus locator |
| Modification time only, hash confirms unchanged | No reparse/rechunk/re-embed; `sources.size_bytes/mtime_ns` are still refreshed as hints |
| Nothing changed (SHA-256, mtime, size, path, and all metadata match) | Zero work — the transaction is never opened, `updated_at_utc` does not move |

A source whose content and metadata are unchanged is still checked for embedding coverage:
`_chunks_missing_active_embedding()` checks whether every existing chunk already has a
`chunk_embeddings` row for the *active* model; if any are missing, those chunks (and only those)
are queued for embedding, without reparsing or rechunking the source at all.

## Three-pass chunk matching

1. **Same source + same logical key.** The common case: a chunk's positional key (page/block index,
   heading-path+paragraph-index, or worksheet+row+part) is unchanged, so its `chunk_id` is reused directly. If its
   `semantic_input_hash` also changed, only that one chunk gets re-embedded.
2. **Unique, unambiguous semantic-hash pairing among what's left.** If content moved to a new
   logical key (e.g. a section reordered), and exactly one remaining old chunk and one remaining
   new candidate share a semantic hash, `chunk_id` and its embedding mapping are preserved. If two
   or more old/new pairs would tie on the same hash, none are guessed — see "ambiguous duplicates"
   below.
3. **Whatever's left** is genuinely new (gets a fresh `chunk_id`) or genuinely removed (deleted,
   cascading its FTS row and `chunk_embeddings` mapping; an `embeddings` row that no chunk
   references any more is deleted later in the same transaction).

Content equality (identical semantic hash) always permits **embedding reuse** — two chunks with
byte-identical repeated text (e.g. duplicated boilerplate) still get two distinct `chunk_id`s but
share one `embeddings` row, so chunk identity is never collapsed even though compute is reused.

### Ambiguous same-hash paths (do not misclassify as a rename)

A rename is only inferred when exactly one removed source path and exactly one added source path share an unambiguous file hash. If two or more removed/added paths would tie on the same hash (e.g. two byte-identical documents both got new paths in the same sync), no rename is inferred for any of them — each new path is added as a new source, and each old path keeps its rows and is reported as missing or unselected until `prune --apply` removes it. Chunk-level embedding reuse still
applies globally through the `(model_id, semantic_input_hash)` cache, so no embedding compute is
wasted even though source-level lineage isn't preserved.

## Transaction sequence

```text
capture immutable parsing snapshots for add/reparse sources
parse only invalidated snapshots
diff old vs new chunks (three-pass matching above)
look up embedding cache; generate only missing embeddings         <- before BEGIN
BEGIN IMMEDIATE
  size/mtime hint updates for otherwise unchanged sources
  unambiguous path updates preserving internal source keys where safe
  per-source: insert new source row (must precede its chunk inserts, FK) or update source
    metadata / chunk deletes / chunk updates (unlink the embedding if the hash changed or `--reembed`) / new
    chunk inserts / pages + assets (add/reparse only)
  link each new or changed chunk to its embedding
  link chunks of unchanged sources that lack an embedding of the active model
  delete embeddings no chunk references any more
  re-stat/re-hash every selected source; ROLLBACK on mismatch
  touch_config()
COMMIT
```

If embedding generation raises, the exception propagates **before** `BEGIN IMMEDIATE` runs, so the
database is provably unchanged (an empty schema may already exist from a prior `connect()` call,
but no `sources`/`chunks`/`embeddings` rows are written). Parsing and PDF rendering use the same
immutable snapshot whose SHA-256 is stored in the source row. If a selected source changes between its first hash and the recheck just before `COMMIT`, the transaction rolls back and the whole `sync()` call returns `SyncReport(status="aborted-source-changed")`. A sync with nothing to write opens no transaction and skips the recheck; the next sync picks up the change.
The unchanged path also verifies SHA-256, so a same-size replacement with a restored nanosecond
mtime cannot remain silently stale. `conn` uses true SQLite autocommit (`isolation_level=None`) precisely so this one explicit
`BEGIN IMMEDIATE`/`COMMIT` pair is the only write transaction in the whole lifecycle; no earlier
read/hint step can leave an implicit transaction open.
