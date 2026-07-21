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

The normal documentation site contains only the original table. An optional embedding-inspection site copies every retained Markdown page, keeps the raw table, and appends the exact text that an embedding pipeline would consume.

## Build boundary

`scripts/build_docs.py` is a repository-specific thin wrapper around the installed Quarto and TraceCite commands. It selects the Python or Julia profile, stages Quarto's retained Markdown, coordinates the optional inspection-site render, and checks retained-Markdown freshness. Normalisation is implemented by the public `tracecite prepare` CLI and package.

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
- Paired Python and Julia executable EDA pages.
- A complete `--keep-embedding-markdown` website copy that can be rendered by a second Quarto run.
- No `.qmd` requirement: executable pages are percent-format `.py` and `.jl`; prose pages are `.md`.

## Build both sites

```bash
python -m pip install -e .
uv run scripts/build_docs.py
```

`uv run` exposes the project environment's installed `tracecite` console script. Use `uv run scripts/build_docs.py --tracecite /path/to/tracecite` to select an explicit executable. When Julia is not installed, the script automatically uses the `python` profile and still builds the Python, format, and architecture pages. With Julia available, it uses the `julia` profile and adds the paired Julia pages to the same website.

After a Quarto render, another project can invoke `tracecite prepare` directly with its retained Markdown root and preparation options.
