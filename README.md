# TraceCite table normalisation

This repository is a single Python/Julia implementation and a multi-page Quarto showcase for source-linked table retrieval.

TraceCite preserves the original table as evidence and derives deterministic, self-describing text for FTS and vector indexing. It does not require humans or agents to manually copy analytical results into prose.

## Core architecture

```text
Python or Julia executable page
    -> Quarto retained Pandoc Markdown
       -> raw table evidence
       -> human HTML site

retained Markdown
    -> TraceCite normaliser
       -> canonical table model
       -> row-oriented retrieval text
       -> diagnostics
       -> optional embedding-inspection website copy
```

The normal site remains pure Quarto output. The generated inspection copy doubles each table only when explicitly requested.

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

## Repository structure

```text
.
├── pyproject.toml
├── Project.toml
├── src/
│   ├── tracecite/
│   │   ├── cli.py
│   │   └── tables/
│   │       ├── models.py
│   │       ├── pandoc.py
│   │       ├── html.py
│   │       ├── normalise.py
│   │       ├── document.py
│   │       ├── render.py
│   │       ├── site.py
│   │       └── publish.py
│   └── TraceCite.jl
├── tests/
├── test/
├── docs/
│   ├── _quarto.yml
│   ├── _quarto-python.yml
│   ├── _quarto-julia.yml
│   ├── guide/
│   ├── formats/
│   ├── python/
│   └── julia/
├── examples/literate_documenter/
└── scripts/build_docs.py
```

The project contains no `.qmd` files. Executable pages use percent-format `.py` and `.jl`; prose pages use `.md`.

## Prerequisites

- Python 3.11 or newer;
- Pandoc, either installed directly or provided by Quarto;
- Quarto for the two documentation-site renders;
- Julia 1.10 or newer only when building the Julia profile.

The Python normaliser and CLI work without Julia. `scripts/build_docs.py` automatically selects the Python-only profile when Julia is not available.

## Install and test

```bash
uv venv
source .venv/bin/activate
uv pip install pip
uv pip install -e .
uv unittest discover -s tests -v
uv build
```

Julia tests:

```bash
julia --project=. -e 'using Pkg; Pkg.instantiate(); Pkg.test()'
```

## Normalise one table

```bash
tracecite table normalise table.md --to text
tracecite table normalise table.html --from html --to debug-markdown
```

## Normalise one document

```bash
tracecite document normalise report.md --to jsonl
tracecite document normalise report.md --to embedding-markdown --output report.embedding.md
```

## Build the human and inspection sites

```bash
uv run scripts/build_docs.py
```

The build script selects one Quarto profile and then performs two site builds:

```text
quarto render docs --profile python   # when Julia is unavailable
# or
quarto render docs --profile julia    # Python + Julia in one site
    -> docs/build/                      human site + retained Markdown

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

## Direct preparation command

```bash
tracecite prepare docs/build \
  --project-config docs/_quarto.yml \
  --project-profile python \
  --source-project docs \
  --keep-embedding-markdown .tracecite/embedding-site \
  --render-embedding-site
```

The generated copy includes `_tracecite/tables.jsonl` and `_tracecite/manifest.json`. Its `_quarto.yml` is derived from the selected human-site profile, preserving theme and navigation while removing execution engines and build hooks. It is disposable, gitignored, and excluded from recursive ingestion.

The copied Markdown is deliberately redundant: it keeps the original table for audit and appends the normalised representation for inspection. Normal indexing can consume `tables.jsonl` or the `NormalisedTable` objects directly without writing the copied site.

## Scope

This repository implements table parsing, canonicalisation, diagnostics, document extraction, and inspection-site generation. It intentionally does not implement model inference, vector storage, or SQLite synchronisation; those layers can consume the stable `NormalisedTable` contract.
