---
title: "From documents to searchable evidence"
---

TraceCite turns documents and workbooks into searchable evidence without requiring a separate prose summary for every table.
A table written directly in Markdown and a table produced by Python or Julia remain available for inspection, while TraceCite can derive retrieval text for full-text and vector search.

Table normalisation, database synchronisation, semantic embedding, hybrid search, integrity diagnostics, and explicit pruning are available through the current package.
PDF evidence also supports selected-page retrieval, indexed page assets, and selected-page derivative PDFs.

## Source material

TraceCite can work with written documents as well as rendered output.

| Input | Role |
|---|---|
| Plain Markdown | Written prose and tables that can be normalised or indexed with heading and line context |
| PDF | Page-local text, page renders, figure crops, and physical-page evidence identity |
| `.xlsx` or `.xlsm` workbook | Stored worksheet values indexed with source hashes and worksheet/A1-range locators |
| Executable Python or Julia | Analysis and narrative that produce tables during execution |
| Retained Markdown | Executed document evidence preserved after rendering |
| HTML | Table-normalisation input from notebooks, Literate.jl, Documenter.jl, and other HTML-producing tools |

: Inputs supported by the documentation and searchable-evidence workflows. {#tbl-document-inputs}

Executable documentation is useful when a table depends on code or changing input data, but it is not a requirement.
A written Markdown file is a first-class source for prose, tables, full-text search, and vector search.

## Written and retained Markdown

Written Markdown and retained Markdown serve different purposes even when both are committed to the repository.

- Written Markdown contains explanations and tables maintained directly in the source document.
- Retained Markdown contains the result of executing and rendering a document. It is generated rather than edited by hand.
- HTML is the presentation layer for browser readers. It can be rebuilt from the source and retained evidence.

Committed retained Markdown makes executed evidence reviewable in ordinary diffs and available without rerunning every analysis. Source-adjacent `*.html.md` files stay beside their executable pages, while ordinary `*.html` files and build directories remain disposable.

The documentation layout is:

```text
docs/
    index.md                       written documentation
    guide/                         written documentation
    examples/python/               executable Python pages
    examples/julia/                executable Julia pages
    guide/architecture.md          written documentation
    guide/architecture.html.md     committed generated evidence
    examples/python/hottest_temperature.html.md  Tutorial 3 inspection output
    build/                         rebuildable HTML website
```

Quarto writes retained Markdown beside each executable source. The public docs
builder copies those files into `docs/build/` for the inspection site. Retained
Markdown is committed; ordinary HTML, `docs/build/`, Quarto caches, and
`.tracecite/` are disposable.

In this repository, `tracecite docs build docs` owns the generic build
orchestration: configured-input discovery, automatic or explicit language
selection, Quarto execution, retained-Markdown staging, inspection export, and
freshness checks. Use `--only python` or `--only julia` for explicit reduced
builds. An external project can run `tracecite prepare` directly after its
Quarto render.

See `examples/report-adoption/aemo-isp-comparison/` for a complete, real
adoption example covering author, check, index, search, doctor, and
publish-only modes together.

## Three separate operations

Normalising a document, synchronising a collection, and computing embeddings are related but distinct operations.

### Normalise

Normalisation is a pure document transformation. It reads Markdown or HTML, discovers tables, and returns:

- the original table source;
- canonical Markdown with a predictable structure;
- table-level retrieval text;
- independently meaningful row records;
- stable table and row identifiers;
- structural diagnostics and content hashes.

Normalisation does not modify a database or call an embedding model.

The public `debug-markdown` output shows raw source, canonical Markdown,
normalised retrieval text, and row records together. It is an inspection text
representation, not a vector.

```bash
tracecite document normalise report.md --to jsonl
```

### Synchronise

`tracecite sync` resolves explicit and manifest-selected sources under a caller-owned root, hashes them, parses only invalidated content, rebuilds locator-aware chunks, and updates FTS5 and sqlite-vec state.
Supported source files are `.pdf`, `.md`, `.xlsx`, and `.xlsm`.

A synchronisation run:

1. resolves explicit source paths and include/exclude globs;
2. hashes selected files and snapshots sources that require parsing;
3. parses changed sources or rebuilds chunks from retained extraction when only chunking metadata changed;
4. reuses unchanged chunks and embeddings where their identities remain valid;
5. commits source, retained extraction, chunk, FTS, vector, and asset changes atomically;
6. reports unavailable selected sources and indexed-but-unselected sources without deleting them.

Synchronisation is incremental, idempotent, and non-pruning.
Removing stored sources requires an explicit `tracecite prune` preview and apply operation.

```bash
tracecite sync \
  --root sources \
  --manifest tracecite-sources.toml \
  --database .tracecite/evidence.sqlite \
  --model-cache-dir .tracecite/model-cache
```

### Embed

Embedding is an internal synchronisation stage rather than a separate public command.
TraceCite generates vectors only for semantic inputs that are missing from the active model's cache.
A model-only change can add the new model's vector coverage without reparsing source files, and `--reembed` forces embedding regeneration when required.

## What becomes searchable

Source formats produce different retrieval units and locators.

- PDF text blocks retain physical-page context and can be associated with validated page renders and figure crops.
- Markdown headings and paragraphs retain heading paths and source line ranges.
- Workbook rows retain worksheet identity and exact A1 ranges; a separate bounding range provides a convenient envelope without implying that every enclosed cell contributed.
- Every indexed source retains its normalised path and SHA-256 so a result can be tied to the indexed file version.

The table-normalisation API separately produces table-level and row-level retrieval text while preserving the original table as evidence.
Those records are useful when a caller needs individual rows to stand alone semantically rather than embedding one large raw table.

## Written and retained representations

The same page may exist as written Markdown and retained Markdown:

```text
docs/guide/architecture.md
docs/guide/architecture.html.md
```

TraceCite treats these as separate source paths when both are selected.
The manifest does not silently infer that a handwritten page and a retained render are one logical record.
Select the authoritative representation for the intended corpus, or use an exclude rule to prevent duplicate full-text and vector results.
A standalone Markdown file without a rendered counterpart uses the written file itself as evidence.

## End-to-end flow

```text
written or retained Markdown ------------------------+
PDF -------------------------------------------------+
OOXML workbook --------------------------------------+----> source-specific parsing
Python or Julia -> committed retained Markdown ------+               |
                                                                     v
                                                        locator-aware chunks
                                                                     |
                                                        database synchronisation
                                                                     |
                                                        FTS5 + semantic vectors
                                                                     |
                                                            hybrid search results
```

The database is derived state. Documents and retained evidence remain inspectable without it, and a configured collection can be rebuilt when the schema, parser, normaliser, or embedding model changes.
