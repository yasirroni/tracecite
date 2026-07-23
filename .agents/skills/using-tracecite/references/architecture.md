# Architecture

## Module layout

```text
tracecite/
  pyproject.toml, uv.lock              # locked dependency truth
  src/tracecite/
    __init__.py
    cli.py                # console entry point: sync, search, page, verify, prune, doctor
    parsers/
      base.py              # ParsedPage / ParsedChunkUnit / ParsedAsset / Parser protocol
      pdf.py                # PyMuPDF-backed extraction, page render, figure crops
      markdown.py
    chunking.py            # greedy char-budget grouping, normalisation, hashing
    schema.py               # versioned schema + path-keyed sources + connect/ensure_schema
    sync.py                 # the whole incremental synchronisation lifecycle
    vector_backend.py        # SqliteVecBackend behind a narrow VectorBackend interface
    verify.py                 # verify quote / verify report
  tests/                   # pytest coverage for package and CLI behaviour
  fixtures/                # stable test fixtures
```

Install the package and use the `tracecite` console script. There is no supported old-name package or command shim.

## Layering

```text
parsers/{pdf,markdown}.py   -- format-specific extraction only, no SQL
        |
chunking.py                 -- format-agnostic grouping + identity hashing, no SQL
        |
sync.py                      -- the only place that opens a write transaction
        |
schema.py + vector_backend.py -- the only places that know SQL/vec0 syntax
```

- `cli.py`, `sync.py`, and `verify.py` depend only on `vector_backend.VectorBackend`'s interface
  (`upsert`, `delete`, `search`, `integrity_check`, `version`, `capabilities`), never on vec0
  virtual-table SQL directly. `tests/test_vector_backend.py` has a contract-test section that
  exercises only this interface, so a future non-sqlite-vec backend could be swapped in without
  touching parsers, chunking, sync, verification, or the CLI.
- `pages` rows (see `references/schema-and-migrations.md`) are the retained parser output. A
  chunker- or normalisation-only change rebuilds chunk-input units straight from `pages.layout_json`
  (via `pdf.units_from_page_layout` / `markdown.units_from_page_layout`) without reopening the
  source file — see `references/synchronisation.md`.

## Explicit-input contract

The CLI never infers a project checkout. Commands that touch a corpus take `--root`, one or more `--manifest` values, `--database`, and `--model-cache-dir` explicitly, or receive those values from an explicitly named profile. Read-only commands such as `search`, `page`, `verify quote`, `verify report`, and `doctor` use the database plus the path/page arguments they need. A host bootstrap may supply defaults, but the package remains repository-neutral.

## Out of scope by design (do not reintroduce)

- An approximate-nearest-neighbour index. Retrieval does an exact k-NN scan through
  `SqliteVecBackend`; see `references/retrieval.md` for why and how bounded filters still work
  without one.
- A second document store (JSONL, a `document.json` per file, LanceDB, DuckDB as the live index).
  `pages`/`chunks` in `tracecite.sqlite` are the only retained parsed representation.
- Deterministic hash vectors as a stand-in for real semantic embeddings.
- OCR, code/notebook/YAML/JSON parser adapters, and a Rust extension/sidecar — all explicitly
  deferred until a representative fixture proves the pure-Python/PyMuPDF/sqlite path is
  insufficient. `parsers/base.py`'s `Parser` protocol is the seam for adding an adapter later.
- A ChatGPT `skill-creator`/`init_skill.py`/`package_skill.py` packaging step — this repository uses
  its own `writing-a-skill` and `auditing-a-skill` checks plus a plain deterministic zip instead
  (see the repository's operator guide).
