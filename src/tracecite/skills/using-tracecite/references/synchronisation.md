# Synchronisation Lifecycle

```text
scan configured paths (explicit manifest entries plus include/exclude globs under --root)
    |
hash each selected source through a stable non-symlink file descriptor
    |
copy every add/reparse source into an immutable per-sync parsing snapshot
    |
parse only changed or invalidated sources
    |
diff old vs new chunks (three-pass matching)
    |
look up the embedding cache and generate only missing embeddings (before any write)
    |
one BEGIN IMMEDIATE ... COMMIT transaction that rechecks source state before COMMIT (skipped if there is nothing to write)
```

`sync.sync()` returns a `SyncReport`: added, reparsed, rechunked, renamed, and unchanged source lists; selected sources whose files are missing; indexed sources the manifest no longer selects; skipped sources with their reason; chunk add, update, and delete counts; `embeddings_generated`; and `status`, which is `"ok"` or `"aborted-source-changed"`.

`sync` never deletes a source. A source whose file is gone, or that the manifest no longer selects, keeps its rows and is listed in `selected_missing_paths` or `indexed_unselected_paths` until `prune --apply` removes it.

## Invalidation rules

| Change | Work |
|---|---|
| File SHA-256 changed | Reparse and rechunk the source |
| Parser metadata changed, even with a byte-identical file | Reparse and rechunk the source |
| Chunker metadata changed only | Rechunk from `pages.layout_json`; the source file is not reopened |
| Normalisation metadata changed | Renormalise and rechunk; re-embed only chunks whose semantic hash changed |
| Embedding model, revision, or dimensions changed | Not done in place. The change requires a schema version bump, and `ensure_schema()` rejects a database with an older version, so the database is rebuilt at a fresh path |
| Path-only rename, or manifest path change with the same content | Update the normalised `path` and keep the internal source key when the match is unambiguous; chunks and embeddings are kept |
| Modification time only, hash unchanged | No reparse, rechunk, or re-embed; `sources.size_bytes` and `mtime_ns` are refreshed as hints |
| Nothing changed (SHA-256, mtime, size, path, and all metadata) | No work; no transaction opens and `updated_at_utc` does not move |

An unchanged source is still checked for embedding coverage. `_chunks_missing_active_embedding()` finds its chunks that have no `chunk_embeddings` row for the database's model, and only those chunks are embedded, without reparsing or rechunking.

## Three-pass chunk matching

1. **Same source and logical key.** The positional key (page and block index, heading path and paragraph index, or worksheet, row, and part) is unchanged, so the `chunk_id` is reused. If its `semantic_input_hash` changed, only that chunk is re-embedded.
2. **Unique semantic-hash pairing among the rest.** When content moved to a new logical key, for example a reordered section, and exactly one remaining old chunk and one remaining new candidate share a semantic hash, the `chunk_id` and its embedding link are kept. When two or more pairs tie on a hash, none is guessed.
3. **The rest** are new (fresh `chunk_id`) or removed. Deleting a chunk cascades to its FTS row and `chunk_embeddings` link. An `embeddings` row that no chunk references is deleted later in the same transaction.

Chunks with the same semantic hash always share one `embeddings` row. Two chunks with byte-identical text, such as repeated boilerplate, keep separate `chunk_id`s.

### Ambiguous same-hash paths

A rename is inferred only when exactly one removed path and one added path share a file hash. When more paths tie on a hash, for example two byte-identical documents that both moved in one sync, no rename is inferred. Each new path is added as a new source, and each old path keeps its rows and is reported as missing or unselected until `prune --apply` removes it. Embeddings are still reused through the `(model_id, semantic_input_hash)` cache, so no embedding is recomputed.

## Transaction sequence

```text
capture immutable parsing snapshots for add/reparse sources
parse only invalidated snapshots
diff old vs new chunks (three-pass matching above)
look up embedding cache; generate only missing embeddings         <- before BEGIN
BEGIN IMMEDIATE
  size/mtime hint updates for otherwise unchanged sources
  unambiguous path updates preserving internal source keys
  per source: insert the source row (before its chunks, FK) or update source metadata /
    chunk deletes / chunk updates (unlink the embedding if the hash changed or `--reembed`) /
    new chunk inserts / pages + assets (add/reparse only)
  link each new or changed chunk to its embedding
  link chunks of unchanged sources that lack an embedding of the database's model
  delete embeddings no chunk references any more
  re-stat/re-hash every selected source; ROLLBACK on mismatch
  touch_config()
COMMIT
```

If embedding generation raises, the exception propagates before `BEGIN IMMEDIATE`, so no `sources`, `chunks`, or `embeddings` rows are written. An empty schema can already exist from an earlier `connect()`.

Parsing and PDF rendering read the same immutable snapshot whose SHA-256 is stored in the source row. If a selected source changes between its first hash and the recheck before `COMMIT`, the transaction rolls back and `sync()` returns `status="aborted-source-changed"`. A sync with nothing to write opens no transaction and skips the recheck; the next sync picks up the change. The unchanged path also checks SHA-256, so a same-size replacement with a restored nanosecond mtime is not missed.

`conn` uses SQLite autocommit (`isolation_level=None`), so the explicit `BEGIN IMMEDIATE`/`COMMIT` pair is the only write transaction and no earlier read or hint step can leave an implicit transaction open.
