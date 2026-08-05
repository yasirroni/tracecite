# TraceCite

TraceCite provides source-linked table normalisation and hybrid evidence retrieval for Markdown, PDF, `.xlsx`, and `.xlsm` sources.

For executable documentation, TraceCite preserves the original table as evidence and derives deterministic, self-describing text for indexing. For source collections, it stores retained extraction, source hashes, full-text search records, semantic vectors, and source-specific locators such as PDF pages, Markdown lines, and workbook worksheet ranges.

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

The searchable-evidence path is separate from the documentation renderer:

```text
declared PDF, Markdown, or workbook sources
    -> retained source extraction
    -> locator-aware chunks
    -> SQLite FTS5 and sqlite-vec
    -> ranked JSON results with source identity and evidence locators
```

## Prerequisites

- Python 3.11 or newer;
- Pandoc, either installed directly or provided by Quarto;
- Quarto for documentation-site renders;
- Julia 1.10 or newer only when building Julia documentation pages.

The Python normaliser and CLI work without Julia. Automatic documentation builds fall back to the Python-only overlay when configured Julia inputs cannot run; explicit Julia-only builds require Julia.

Evidence synchronisation and hybrid search use the optional `evidence` dependencies:

```sh
uv pip install -e ".[evidence]"
```

Workbook parsing reads OOXML packages directly with the Python standard library and runs independently of Excel, Julia, Quarto, and third-party workbook readers.

## Usage

The public `tracecite` CLI provides table and document normalisation, documentation builds, and source-evidence synchronisation and search. The `prepare` command consumes retained Markdown after a Quarto render and creates the optional inspection-site copy.

### Public API

```python
from tracecite.tables import (
    normalise_pandoc_table,
    normalise_html_table,
    normalise_document_tables,
)
```

`normalise_pandoc_table()` is the core contract. It accepts one Pandoc table and returns raw evidence, canonical Markdown, normalised text, row records, diagnostics, hashes, and version metadata.

Each row also receives a deterministic `row_id`. When `row_identity` metadata is supplied, the identifier follows the logical row rather than its current rank or position.

`normalise_html_table()` supports Literate.jl, Documenter.jl, PrettyTables, notebook HTML MIME, row spans, and column spans through an HTML-to-canonical-Markdown adapter.

### Index and search source evidence

Declare the source collection in a manifest. Explicit sources and include/exclude globs may select `.pdf`, `.md`, `.xlsx`, and `.xlsm` files.

```toml
schema_version = 1

[[source]]
path = "2023-iasr-ev-workbook.xlsx"
```

Synchronise the selected sources into a database, search the resulting lexical and semantic index, then run the integrity checks:

```sh
tracecite sync \
  --root sources \
  --manifest tracecite-sources.toml \
  --database .tracecite/evidence.sqlite \
  --model-cache-dir .tracecite/model-cache

tracecite search \
  "weekday versus weekend electric vehicle charging behaviour" \
  --database .tracecite/evidence.sqlite \
  --model-cache-dir .tracecite/model-cache

tracecite doctor --database .tracecite/evidence.sqlite
```

`sync` is incremental and non-pruning. Unavailable or no-longer-selected sources remain in the database until an explicit `tracecite prune` operation is previewed and applied.

Search results include retrieval provenance and a source-specific locator. The abbreviated JSON below shows the stable workbook evidence fields; the actual worksheet and ranges depend on the indexed workbook and chunk configuration.

```json
{
  "source_path": "inputs-and-assumptions.xlsx",
  "source_type": "workbook",
  "source_sha256": "<64-character SHA-256>",
  "locator": {
    "kind": "excel-range",
    "sheet": "<worksheet name>",
    "range": "<bounding A1 range>",
    "range_kind": "bounding",
    "exact_ranges": ["<exact A1 range>"]
  },
  "provenance": ["lexical", "vector"]
}
```

The source path and SHA-256 identify the workbook version. The worksheet and `exact_ranges` identify the cells represented in the indexed passage. `range` is only the convenient bounding rectangle and can include cells that did not contribute to the passage. Search rank identifies candidate evidence; inspect the returned cells before using the result to support a claim.

The portable workbook citation is the source path and SHA-256 together with the worksheet and A1 ranges. Exact-range opening is handled by the workbook viewer or by a provider-specific link supplied separately.

#### Workbook boundaries

- `.xlsx` and `.xlsm` OOXML packages are supported. Legacy binary `.xls` files are outside the supported source set.
- Stored text, numeric, Boolean, error, formula, and cached formula values are retained. Cached values describe the workbook's stored state; TraceCite does not recalculate formulae.
- The parser reads stored package content only. It does not execute VBA or refresh external links, Power Query, pivot caches, or data connections.
- Style-only empty cells are ignored. Excel display formatting is not reconstructed, so styled date or time serials can remain numeric.
- Workbook chunks are row-oriented. The parser does not yet infer formal Excel tables or propagate complex multi-row headers into every row.

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

`tracecite page` reads retained PDF page text from the SQLite evidence database. Omitting the selector returns physical page 1. A selector can combine individual pages, closed ranges, and open ranges; overlapping terms are deduplicated and returned in ascending physical-page order.

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

`examples/report-adoption/aemo-isp-comparison/docs/tracecite.toml` demonstrates the documentation evidence contract. Schema version 1 defines exactly `authored_root`, `retained_root`, `staged_root`,
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
uv pip install -e ".[evidence,test]"
```

To build the whole `docs/`, Julia environment is needed.

```sh
julia --project=. -e 'using Pkg; Pkg.instantiate()'
```

### Test

Python tests and build:

```sh
python -m pytest
uv build
```

Julia test:

```sh
julia --project=. -e 'using Pkg; Pkg.instantiate(); Pkg.test()'
```
