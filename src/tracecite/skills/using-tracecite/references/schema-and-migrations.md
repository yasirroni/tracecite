# Schema, Configuration, and Evidence Identity

## Database path

`--database` names a SQLite file the caller owns, at any path. Databases and SQLite sidecars are generated runtime files; never commit them.

TraceCite does not migrate. A database with another schema version is rejected; rebuild it at a fresh path. Old bootstrap or indexer schemas, old package and command names, and caller-managed evidence-label contracts are not supported.

## Evidence identity

- PDF and Markdown evidence: the normalised root-relative POSIX source path plus a physical page or line locator.
- Workbook evidence: the normalised source path and indexed SHA-256 plus the worksheet and exact A1 ranges in `locator_json`.
- Internal keys such as `source_pk`, page row IDs, chunk IDs, and asset IDs are private.
- Markdown reference labels are opaque. A report citation counts because its reference definition points to a local path with a positive `#page=N` fragment, not because of its label.
- Source-link registries use schema version 3 and match by `local_path`.

## Manifest

Manifests are layered and hold explicit paths, include globs, and exclude globs:

```toml
schema_version = 1

[[source]]
path = "reports/overview.md"

[[include]]
glob = "reports/**/*.pdf"

[[include]]
glob = "workbooks/**/*.xlsx"

[[include]]
glob = "workbooks/**/*.xlsm"

[[exclude]]
glob = "reports/drafts/**"
```

TraceCite rejects absolute paths, paths that escape the root (including through a symlink), unsupported extensions, and unknown fields. Duplicate normalised entries collapse into one. Sync skips symlinked files and reports them in `skipped_sources`. Selection rules apply to files on disk and to paths already in the database. A selected path whose file is gone stays indexed until `tracecite prune` removes it.

## Stored tables

- configuration: schema, parser, chunker, and model versions, and update timestamps;
- `sources`, keyed internally by `source_pk`, with a unique normalised `path`;
- retained `pages` text and PDF, Markdown, or workbook layout;
- `chunks`, FTS5 content, embeddings, sqlite-vec vectors, and chunk-to-embedding links;
- generated PDF assets with their SHA-256.

`tracecite doctor` checks relational consistency, vector and FTS state, asset existence, and asset hashes.
