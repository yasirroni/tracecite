---
title: "From documents to searchable evidence"
---

TraceCite turns documents into searchable evidence without requiring a separate prose summary for every table. A table written directly in Markdown and a table produced by Python or Julia follow the same path once they appear in a document: the original table remains available for inspection, while TraceCite derives records that work better for full-text search and future vector search.

Table normalisation and the inspectable embedding-site copy are available in the current package. Their current output is pre-vector retrieval text. Database synchronisation and embedding storage describe the planned indexing path; they are not yet exposed as TraceCite commands.

## Source material

TraceCite can work with written documents as well as rendered output.

| Input | Role |
|---|---|
| Plain Markdown | Written prose and tables that can be consumed directly |
| Executable Python or Julia | Analysis and narrative that produce tables during execution |
| Retained Markdown | Executed document evidence preserved after rendering |
| HTML | Tables from notebooks, Literate.jl, Documenter.jl, and other HTML-producing tools |

: Document inputs supported by the evidence pipeline. {#tbl-document-inputs}

Executable documentation is useful when a table depends on code or changing input data, but it is not a requirement. A written Markdown file is a first-class source for prose, tables, full-text search, and future vector search.

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

Synchronisation is the planned end-to-end database operation. It will compare declared sources with stored records, add new material, update changed material, and remove records for deleted material within the declared source scope.

A synchronisation run will:

1. discover documents declared by a manifest;
2. parse and chunk ordinary prose;
3. find and normalise tables;
4. create table-level and row-level retrieval records;
5. update document, table, row, and full-text-search records;
6. remove stale records from the same managed source scope;
7. compute and store embeddings when an embedding model is configured.

This is a convergence operation rather than an append-only import. Running it again against unchanged inputs should leave the indexed collection unchanged.

### Embed

Embedding converts retrieval records into vectors. It is planned as a separate internal stage so a changed embedding model does not require documents to be reparsed or tables to be normalised again.

When embeddings are enabled during synchronisation, only new or changed retrieval records need new vectors. A separate embedding command can later support model migrations and repair missing vectors.

## What becomes searchable

Ordinary prose and tables need different retrieval units.

- Prose is split into chunks that retain document and section context.
- Each table has a table-level record containing its caption, headers, units, section, and overall meaning.
- Each row has a row-level record that repeats enough table and column context to stand on its own in search results.
- The raw table remains attached as evidence and is not replaced by the derived text.

A single large vector for the raw table would make individual observations difficult to retrieve. Table-level and row-level records allow a search to find either the whole table or one relevant row while preserving a link to the original table.

## One logical document

The same page may exist as written Markdown and retained Markdown:

```text
docs/guide/architecture.md
docs/guide/architecture.html.md
```

These files represent one logical document, not two independent search results. A source manifest can record the written path for provenance and the retained path as the indexable evidence. A standalone Markdown file without a rendered counterpart uses the written file itself as its evidence.

Logical document identity prevents duplicate full-text and vector results while preserving the relationship between source, execution, and rendered evidence.

## End-to-end flow

```text
written Markdown -----------------------------------+
                                                     |
Python or Julia -> committed retained Markdown -----+
                                                     |
                                                     v
                                      document and table normalisation
                                                     |
                         +---------------------------+------------------+
                         |                                              |
                  prose chunks                              table and row records
                         |                                              |
                         +---------------------------+------------------+
                                                     |
                                          database synchronisation
                                                     |
                                    full-text search and optional vectors
```

The database is derived state. Documents and retained evidence remain inspectable without it, and a configured collection can be rebuilt when the schema, parser, normaliser, or embedding model changes.
