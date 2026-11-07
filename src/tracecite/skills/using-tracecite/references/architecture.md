# Architecture

Read this before changing TraceCite itself.

## Module layout

```text
tracecite/
  pyproject.toml, uv.lock   # locked dependency truth
  src/tracecite/
    cli.py                  # command parser and router for every subcommand
    __main__.py             # python -m tracecite
    skills/                 # bundled agent skills, copied by `tracecite skills install`
    evidence/
      commands.py           # sync, search, page, extract-pages, verify, prune, doctor
      config.py             # profile TOML loading
      manifest.py           # [[source]]/[[include]]/[[exclude]] rules and source selection
      paths.py              # root-relative path normalisation and file hashing
      parsers/
        base.py             # ParsedPage, ParsedChunkUnit, ParseResult, units_from_layout
        pdf.py              # PyMuPDF extraction with OCR fallback, page render, figure crops
        markdown.py
        workbook.py         # OOXML worksheet and A1-range extraction
      chunking.py           # character-budget grouping, normalisation, hashing
      embedding.py          # sentence-transformers embedding model
      schema.py             # versioned schema, connect, ensure_schema
      sync.py               # incremental synchronisation and prune apply
      vector_backend.py     # SqliteVecBackend: all vec0 queries
      page_selection.py     # physical page selector grammar
      page_output.py        # validated page and crop result payloads
      page_extraction.py    # selected-page derivative PDFs and manifests
      source_links.py       # schema-v3 source-link registry
      verify.py             # verify quote, verify report
  tests/                    # pytest suite; fixtures in tests/fixtures/
```

## Layering

```text
parsers/{pdf,markdown,workbook}.py  -- format-specific extraction, no SQL
        |
chunking.py                         -- format-agnostic grouping and identity hashing, no SQL
        |
sync.py                             -- the only module that writes evidence rows
        |
vector_backend.py                   -- the only module that queries vec0 (schema.py creates the table)
```

- `commands.py` and `sync.py` reach vectors only through `SqliteVecBackend` (`upsert`, `delete`, `search`, `integrity_check`).
- `pages` rows are the retained parser output. A chunker- or normalisation-only change rebuilds chunk units from `pages.layout_json` (`pdf.units_from_page_layout` for PDFs, `base.units_from_layout` for Markdown and workbooks) without reopening the source file.

## Package rules

- The CLI never infers a project checkout. Corpus commands take `--root`, `--manifest`, `--database`, and `--model-cache-dir`, or a named profile. Read-only commands need only the database and their path and page arguments. A host may supply defaults, but the package stays repository-neutral.
- Do not add aliases for old package or command names.
- Help commands stay lightweight. They must not import or touch parsers, PDF or OCR code, embeddings, sqlite-vec, manifests, databases, projects, caches, or the network.

## Out of scope by design (do not reintroduce)

- An approximate-nearest-neighbour index. Retrieval runs exact k-NN through `SqliteVecBackend`; see `references/retrieval.md`.
- A second document store (JSONL, a `document.json` per file, LanceDB, or DuckDB as the live index). `pages` and `chunks` in the SQLite database are the only retained parsed representation.
- Deterministic hash vectors in place of real semantic embeddings.
- Code, notebook, YAML, or JSON parser adapters, and a Rust extension or sidecar, until a representative fixture shows that the pure-Python, PyMuPDF, and SQLite path is not enough. A new adapter returns a `ParseResult` from `parsers/base.py` and is registered in `sync._parser`.
