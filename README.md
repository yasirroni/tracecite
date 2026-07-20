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
    -> TraceCite normaliser
       -> canonical table model
       -> row-oriented retrieval text
       -> diagnostics
       -> optional embedding-inspection website copy
```

The normal site remains pure Quarto output. The generated inspection copy doubles each table only when explicitly requested.

## Prerequisites

- Python 3.11 or newer;
- Pandoc, either installed directly or provided by Quarto;
- Quarto for the two documentation-site renders;
- Julia 1.10 or newer only when building the Julia profile.

The Python normaliser and CLI work without Julia. `scripts/build_docs.py` automatically selects the Python-only profile when Julia is not available.

## Usage

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
```

Julia dependency installation is required once before building the combined Python and Julia site. To build only the Python pages, use:

```sh
uv run scripts/build_docs.py --skip-julia
```

The build script selects one Quarto profile and then performs two site builds:

```text
quarto render docs --profile python   # when Julia is unavailable
# or
quarto render docs --profile julia    # Python + Julia in one site
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

If Julia is unavailable, the build script selects the `python` profile without deleting or modifying the Julia sources. When Julia is available, it selects the `julia` profile, which enables Quarto's native Julia engine and adds the paired Julia pages to the same site.
