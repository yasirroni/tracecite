---
title: "TraceCite table normalisation"
---

TraceCite treats generated documentation as a reusable analytical knowledge layer. Executable `.py` and `.jl` pages remain the computational authority. Quarto retains their executed Pandoc Markdown and produces the documentation website. TraceCite then preserves each raw table and derives a deterministic retrieval representation without mutating the original site.

## Two representations, one result

```text
.py / .jl
    -> Quarto execution
    -> retained Pandoc Markdown with raw tables
    -> HTML website

retained Markdown
    -> `tracecite prepare` CLI/package
    -> raw table evidence + normalised row text
    -> future FTS/vector/SQLite ingestion
```

The normal documentation site contains only the original table. An optional embedding-inspection site copies every retained Markdown page, keeps the raw table, and appends the exact normalised retrieval text prepared for a future embedding pipeline; it does not contain vectors.

## Build boundary

`tracecite docs build docs` is the public automatic builder. It discovers configured executable inputs, selects the complete site or a safe reduced fallback, stages retained Markdown, and optionally renders the inspection site. Use its `--only python` and `--only julia` options for explicit reduced builds.

| Representation | Preserved content | Main consumer | Default location |
|---|---|---|---|
| Raw Pandoc or HTML table | Original rows, columns, units, alignment, caption, and visible anomalies | Search tools and auditors | Quarto retained Markdown |
| Normalised retrieval text | Repeated field labels, table and section context, row identities, and diagnostics | FTS/vector ingestion | `NormalisedTable` and `_tracecite/tables.jsonl` |
| HTML table | Quarto styling, navigation, captions, and browser presentation | Readers | `docs/build/` |
| Embedding inspection copy | Raw table followed by the exact derived representation | Developers validating the transform | `.tracecite/embedding-site/` |

: The four representations produced or consumed by the showcase. {#tbl-showcase-representations}

## What this repository demonstrates

- Native Pandoc pipe, grid, and multiline table parsing through Pandoc's AST.
- HTML table conversion for Literate.jl, Documenter.jl, PrettyTables, and notebook HTML MIME output.
- Explicit diagnostics for spans, duplicate ranks, mixed units, declared ordering, empty headers, and malformed structures.
- Four executable tutorials: what TraceCite does, the optional Julia route, ranked-result normalisation and inspection, and Quarto code visibility.
- Two source-backed examples under `docs/examples/`: semantic workbook retrieval and an end-to-end AEMO report-adoption workflow.
- The Python-only build includes the ranked-results tutorial in
  `examples/python/hottest_temperature.py`.
- A complete `--keep-embedding-markdown` website copy that can be rendered by a second Quarto run.
- No project-wide `.qmd` requirement: executable tutorials use percent-format `.py` and `.jl`, prose pages use `.md`, and the report-adoption example uses one `.qmd` source to demonstrate an external Quarto authoring workflow.

## Build the documentation and inspection sites

```bash
python -m pip install -e .
uv run tracecite docs build docs
uv run tracecite docs build docs --only python
julia --version
uv run tracecite docs build docs --only julia
```

The public builder uses the complete base Quarto configuration when both
runtimes are available. If Julia is unavailable, it warns with every skipped
configured Julia source and uses the Python-only overlay. Explicit reduced
builds use the two `--only` commands above. Projects that already have
rendered and staged retained Markdown can invoke `tracecite prepare` directly.

After a Quarto render, another project can invoke `tracecite prepare` directly with its retained Markdown root and preparation options.
