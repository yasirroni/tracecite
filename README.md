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

`tracecite docs build docs` is the public automatic documentation builder. It discovers configured executable inputs, selects the complete site when runtimes are available, safely falls back with exact skipped-file warnings, stages retained Markdown, and optionally renders the inspection site. The three fixed repository scripts are convenient entry points; table normalisation remains in the public `tracecite prepare` command.

## Prerequisites

- Python 3.11 or newer;
- Pandoc, either installed directly or provided by Quarto;
- Quarto for documentation-site renders;
- Julia 1.10 or newer only when building the Julia profile.

The Python normaliser and CLI work without Julia. Automatic documentation builds fall back to the Python-only overlay when configured Julia inputs cannot run; explicit Julia-only builds require Julia.

## Usage

The public `tracecite` CLI provides table and document normalisation directly; the `prepare` command consumes retained Markdown after a Quarto render and creates the optional inspection-site copy.

## Public API

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

### Build the documentation and inspection sites

```sh
julia --project=. -e 'using Pkg; Pkg.instantiate()'
uv run scripts/build_docs.py
uv run scripts/build_docs_python.py
julia --version
uv run scripts/build_docs_julia.py
```

The automatic script invokes the installed package in-process. The public equivalent is `tracecite docs build docs`; use `--only python` or `--only julia` for explicit reduced builds. External projects can invoke `tracecite prepare` directly after their Quarto render when they already have rendered and staged retained Markdown.

Julia dependency installation is required once before building the combined Python and Julia site. To build only the Python pages, use:

```sh
uv run tracecite docs build docs --only python
```

The builder selects the complete site or a reduced overlay, runs Quarto, stages retained Markdown, and calls the existing inspection export directly. The optional second render remains controlled by the builder:

```text
tracecite docs build docs             # automatic complete/fallback selection
tracecite docs build docs --only python
tracecite docs build docs --only julia
    -> docs/build/                      documentation site + retained Markdown

tracecite prepare docs/build \
    --project-config docs/_quarto.yml \
    --project-profile python \
    --source-project docs \
    --keep-embedding-markdown .tracecite/embedding-site \
    --render-embedding-site
    -> .tracecite/embedding-site/       copied and augmented Markdown
    -> .tracecite/embedding-site/_site/ rendered inspection site
```

If Julia is unavailable, the automatic build names every configured Julia source it skips and renders the Python overlay without modifying Julia sources. The Julia-only script is a reusable entry-point pattern for Julia packages such as PISP.jl.

To open the final docs:

```sh
open docs/build/index.html
```
