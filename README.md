# TraceCite table normalisation

This repository is a single Python/Julia implementation and a multi-page Quarto showcase for source-linked table retrieval.

TraceCite preserves the original table as evidence and derives deterministic, self-describing text for FTS and vector indexing. Analytical results do not need to be copied into separate prose.

## Core architecture

```text
Python or Julia executable page
    -> Quarto retained Pandoc Markdown
       -> raw table evidence
       -> HTML site

retained Markdown
    -> `tracecite prepare` CLI/package
       -> canonical table model
       -> row-oriented retrieval text
       -> diagnostics
       -> optional embedding-inspection website copy
```

The normal site remains pure Quarto output. The generated inspection copy doubles each table only when explicitly requested.

`tracecite docs build docs` is the public automatic documentation builder. It discovers configured executable inputs, selects the complete site when runtimes are available, safely falls back with exact skipped-file warnings, stages retained Markdown, and optionally renders the inspection site. Table normalisation remains in the public `tracecite prepare` command.

## Prerequisites

- Python 3.11 or newer;
- Pandoc, either installed directly or provided by Quarto;
- Quarto for documentation-site renders;
- Julia 1.10 or newer only when building Julia documentation pages.

The Python normaliser and CLI work without Julia. Automatic documentation builds fall back to the Python-only overlay when configured Julia inputs cannot run; explicit Julia-only builds require Julia.

## Usage

The public `tracecite` CLI provides table and document normalisation directly; the `prepare` command consumes retained Markdown after a Quarto render and creates the optional inspection-site copy.

### Public API

```python
from tracecite.tables import (
    normalise_panTraceCiteTables,
    normalise_html_table,
    normalise_document_tables,
)
```

`normalise_pandoc_table()` is the core contract. It accepts one Pandoc table and returns raw evidence, canonical Markdown, normalised text, row records, diagnostics, hashes, and version metadata.

Each row also receives a deterministic `row_id`. When `row_identity` metadata is supplied, the identifier follows the logical row rather than its current rank or position.

`normalise_html_table()` supports Literate.jl, Documenter.jl, PrettyTables, notebook HTML MIME, row spans, and column spans through an HTML-to-canonical-Markdown adapter.

### Normalise one table

```sh
tracecite table normalise table.md --to text
tracecite table normalise table.html --from html --to debug-markdown
```

### Normalise one document

```sh
tracecite document normalise report.md --to jsonl
tracecite document normalise report.md --to embedding-markdown --output report.embedding.md
```

### Retrieve retained pages and visual evidence

`tracecite page` reads retained page text from the SQLite evidence database. Omitting the selector returns physical page 1. A selector can combine individual pages, closed ranges, and open ranges; overlapping terms are deduplicated and returned in ascending physical-page order.

```sh
tracecite page reports/example.pdf --database evidence.sqlite
tracecite page reports/example.pdf 5,12-15,20 --database evidence.sqlite
tracecite page reports/example.pdf 97- --database evidence.sqlite
tracecite page reports/example.pdf -20 --database evidence.sqlite
tracecite page reports/example.pdf all --database evidence.sqlite
```

The standalone selector `all` is the only implicit complete-source form; it cannot be combined with another term. Multi-page text output marks each physical page. `--format json` returns an ordered array containing retained text, extraction metadata, a citation link, and validated paths for the indexed page render and figure crops. Search results expose the same page-render and figure-crop fields for page-local PDF matches.

`extract-pages` uses the same selector grammar but reads the indexed source PDF to create a derivative PDF and provenance manifest. The output directory must already exist outside the source root. TraceCite refuses stale source content, symlink output directories, overlap, and overwrite.

```sh
mkdir -p ../tracecite-exports
tracecite extract-pages reports/example.pdf 5,12-15,20 \
  --database evidence.sqlite \
  --output-dir ../tracecite-exports
```

Use database-backed text or indexed page assets for page-local questions. Select `all` only when the complete source is intentionally required.

### Build the documentation

```sh
tracecite docs build docs
tracecite docs build docs_quarto_py --only python
tracecite docs build docs_quarto_jl --only julia
```

<!-- TODO:
Explain the expected `[WARNING] Could not fetch resource`
-->

The public builder discovers configured render inputs, automatically selects the complete site when both runtimes are available, and safely falls back to the available language with exact skipped-file warnings.
Use `--only python` or `--only julia` for explicit reduced builds.
External projects can invoke `tracecite prepare` directly after their Quarto render when they already have rendered and staged retained Markdown.

See `examples/report-adoption/aemo-isp-comparison/` for a complete, real example of the author -> check -> index -> search -> doctor -> publish-only workflow using two AEMO Integrated System Plan reports.

Repository integrations may validate the docs evidence contract before building:

```sh
tracecite docs build docs --docs-config docs/tracecite.toml --repo-root .
```

Schema version 1 defines exactly `authored_root`, `retained_root`, `staged_root`,
`source_links`, `index_output`, `publication_exclude`, and optional
`host_render_command` under `[docs]`. Contract paths are repository-relative and
must remain contained within the repository.

If Julia is unavailable, the automatic build names every configured Julia source it skips and renders the Python overlay without modifying Julia sources.

To open the final docs:

```sh
open docs/build/index.html
```

### Direct preparation command

```sh
tracecite prepare docs/build \
  --project-config docs/_quarto.yml \
  --project-profile python \
  --source-project docs \
  --keep-embedding-markdown .tracecite/embedding-site \
  --render-embedding-site
```

The generated copy includes `_tracecite/tables.jsonl` and `_tracecite/manifest.json`. Its `_quarto.yml` is derived from the selected documentation profile, preserving theme and navigation while removing execution engines and build hooks. It is disposable, gitignored, and excluded from recursive ingestion.

The copied Markdown is deliberately redundant: it keeps the original table for audit and appends the normalised representation for inspection. Normal indexing can consume `tables.jsonl` or the `NormalisedTable` objects directly without writing the copied site.

## Contributing

### Environment

The core package is fully operated under Python.

```sh
uv venv
source .venv/bin/activate
uv pip install pip
uv pip install -e .
```

To build the whole `docs/`, Julia environment is needed.

```sh
julia --project=. -e 'using Pkg; Pkg.instantiate()'
```

### Test

Python tests and build:

```sh
uv unittest discover -s tests -v
uv build
```

Julia test:

```sh
julia --project=. -e 'using Pkg; Pkg.instantiate(); Pkg.test()'
```
