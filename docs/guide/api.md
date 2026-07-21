---
title: "Python API and CLI"
---

## Core function

```python
from tracecite.tables import normalise_pandoc_table

table = normalise_pandoc_table(markdown_table)
print(table.normalised_text)
```

The ranked-results tutorial demonstrates this API end to end, including the
public `debug-markdown` representation in the Python-only build:
`examples/python/hottest_temperature.py`.

The result contains:

- `raw_source` — exact evidence supplied to the function;
- `canonical_markdown` — deterministic flat Markdown;
- `normalised_text` — table-level retrieval text;
- `row_ids` — stable per-row identifiers, using configured logical keys where available;
- `row_records` — independently interpretable row text;
- `diagnostics` — structural and semantic warnings or errors;
- `source_hash` and `normaliser_version` — incremental rebuild keys.

## HTML adapter

```python
from tracecite.tables import normalise_html_table

table = normalise_html_table(documenter_html)
```

The HTML adapter expands row and column spans, records diagnostics, preserves the original HTML, and then uses the same Pandoc-table normal form.

## Whole-document extraction

```python
from tracecite.tables import normalise_document_tables

tables = normalise_document_tables(
    markdown,
    document_path="docs/build/examples/python/weather.html.md",
    source_code_path="docs/examples/python/weather.py",
)
```

## CLI

```bash
tracecite table normalise table.md --to text
tracecite table normalise table.html --from html --to debug-markdown
tracecite document normalise report.md --to jsonl
tracecite check docs/build
```

Pandoc is authoritative. `--allow-pipe-fallback` is an explicit reduced mode for ordinary pipe tables when neither standalone Pandoc nor Quarto's bundled Pandoc is available.

## Prepare the inspectable copy

For a repository with Quarto sources, the automatic builder is:

```bash
tracecite docs build docs
tracecite docs build docs --only python
tracecite docs build docs --only julia
```

It discovers configured render inputs and performs Quarto execution, retained
Markdown staging, and optional inspection export. Use the direct `prepare`
command below when a site has already been rendered and staged.

```bash
tracecite prepare docs/build \
  --project-config docs/_quarto.yml \
  --project-profile python \
  --source-project docs \
  --keep-embedding-markdown .tracecite/embedding-site \
  --render-embedding-site
```

The selected profile is merged into the copied site's configuration. Navigation, theme, brand, and ordinary website settings are retained. Execution engines and pre/post-render hooks are removed because the copied Markdown already contains executed results.

`debug-markdown` and the embedding inspection site expose normalised retrieval
text, raw and canonical representations, and row records. They do not generate
or display embedding vectors.
