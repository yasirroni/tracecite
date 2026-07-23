# Schema, Configuration, and Path/Page Evidence Identity

## Database-path model

`--database` names the SQLite file the caller owns. Repository-neutral callers may choose any path. Databases and SQLite sidecars remain generated runtime artifacts and must not be committed.

TraceCite uses a fresh schema. It does not migrate or accept old bootstrap/indexer schemas, old package names, old command names, or caller-managed evidence-label contracts.

## Evidence identity

- Public evidence identity is the normalised root-relative POSIX source path plus a physical PDF page or Markdown line locator.
- Internal keys such as `source_pk`, page row IDs, chunk IDs, and asset IDs are private implementation details.
- Markdown reference labels are opaque. A report citation is authoritative because its reference definition points to a local path and positive `#page=N` fragment, not because the label encodes an ID.
- Source-link registries use schema version 2 and match by `local_path`.

## Manifest contract

Manifests are layered and may contain explicit paths, include globs, and exclude globs:

```toml
schema_version = 1

[[source]]
path = "reports/overview.md"

[[include]]
glob = "reports/**/*.pdf"

[[exclude]]
glob = "reports/drafts/**"
```

TraceCite rejects absolute paths, traversal, unsupported extensions, unknown fields, duplicate normalised entries, and symlink escapes. Selection rules apply both to files currently on disk and to paths already stored in the database; unavailable selected paths are retained rather than pruned automatically.

## Stored tables

At a high level the schema stores:

- configuration metadata, parser/chunker/model versions, and update timestamps;
- `sources`, keyed internally by `source_pk` with unique normalised `path`;
- retained `pages` text and PDF/Markdown locators;
- `chunks`, FTS5 content, embeddings, sqlite-vec vectors, and chunk-to-embedding links;
- generated PDF assets with stored SHA-256 hashes.

Use `tracecite doctor` to verify relational consistency, vector/FTS state, asset existence, and asset hashes after syncs or restores.
