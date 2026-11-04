# TraceCite

TraceCite is a Python package and CLI that turns executable documentation, and the PDF, Markdown, and Excel source documents behind it, into evidence that people and AI agents can read, search, cite, and verify.

Its core is source-linked table normalisation. Each table in a rendered Python or Julia documentation page stays in the site as the original evidence. TraceCite derives deterministic, self-describing row text from the table for search, so generated tables become retrievable without changing what readers see.

Around that core, TraceCite indexes source collections of Markdown, PDF, `.xlsx`, and `.xlsm` files. It stores the retained extraction, source hashes, full-text and vector search records, and source-specific locators such as PDF pages, Markdown lines, and worksheet ranges. It verifies quotations and report citations against these records.

Two documentation commands join the two parts. `tracecite docs index` adds a project's retained documentation, with its normalised tables, to an evidence index. `tracecite docs stage` routes source links to local files or public URLs.

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

The normal site remains pure Quarto output. The inspection copy, which doubles each table, is generated only on explicit request.

`tracecite docs build docs` is the public automatic documentation builder. It discovers configured executable inputs, selects the complete site when both runtimes are available, safely falls back to the available language with exact skipped-file warnings, stages retained Markdown, and optionally renders the inspection site. Table normalisation remains in the public `tracecite prepare` command.

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

### Index and search source evidence

Declare the source collection in a manifest. Explicit sources and include or exclude globs select `.pdf`, `.md`, `.xlsx`, and `.xlsm` files.

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

#### Sync

- `sync` needs at least one `[[source]]` or `[[include]]` rule. Without one, it stops before creating or changing the database.
- It prints each added, reparsed, renamed, missing, or unselected path on its own line. `--json` prints the whole report as JSON.
- When a declared `[[source]]` does not exist under the root, sync still applies the other sources, lists the path under `missing-sources`, and exits with status 1. A sync of one source path checks only that path.
- PDF pages that yield no text, such as blank or scanned pages, are listed under `pages-without-text`. OCR of scanned pages needs [Tesseract](https://github.com/tesseract-ocr/tesseract); without it, sync stores those pages without text. After installing Tesseract, re-run `tracecite sync --full` to extract their text.
- `sync` is incremental and non-pruning. Unavailable or no-longer-selected sources remain in the database, still searchable and citable, until an explicit `tracecite prune` is previewed and applied.

#### Prune

A prune needs the source root (`--root` or a profile). It plans every indexed source that the rules no longer select or whose file no longer exists under the root; the preview lists the latter under `missing_paths`. `--all` plans every indexed source without a root. `prune --apply` compacts the database file afterwards.

#### Doctor

`doctor --root <dir>` also compares each indexed source with its file and warns about sources that changed or disappeared since the last sync. These warnings do not change the exit status; only database, vector, and asset integrity issues do.

#### Search

`--source-type` restricts `search` to one or more source types (`pdf`, `markdown`, or `workbook`; repeatable). The filter applies before lexical and vector candidates are ranked and truncated to `--limit`, not as a post-hoc filter on the final result list:

```sh
tracecite search "coal retirement" \
  --database .tracecite/evidence.sqlite \
  --source-type pdf
```

- A query must contain text; an empty query exits with status 2.
- `--lexical-only` ranks by full-text search alone and skips loading the embedding model.
- Chinese, Japanese, and Korean (CJK) text has no spaces between words, so lexical search also matches each CJK run of the query as a substring of the indexed text. That match reads every indexed passage, so it is slower than ordinary full-text search on a large database.
- The embedding model is English-only, so CJK queries rely on the lexical match.
- Hits from byte-identical files at different paths are reported once, under the best-ranked path, with the other paths in `duplicate_paths`.

Each search result includes retrieval provenance and a source-specific locator. The abbreviated JSON below shows the stable workbook evidence fields; the actual worksheet and ranges depend on the indexed workbook and chunk configuration.

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

The portable workbook citation is the source path, SHA-256, worksheet, and A1 ranges. The workbook viewer, or a provider-specific link supplied separately, opens the exact range.

#### Workbook boundaries

- `.xlsx` and `.xlsm` OOXML packages are supported. Legacy binary `.xls` files are outside the supported source set.
- Stored text, numeric, Boolean, error, formula, and cached formula values are retained. Cached values describe the workbook's stored state; TraceCite does not recalculate formulae.
- The parser reads stored package content only. It does not execute VBA or refresh external links, Power Query, pivot caches, or data connections.
- Style-only empty cells are ignored. Excel display formatting is not reconstructed, so styled date or time serials can remain numeric.
- Workbook chunks are row-oriented. The parser does not yet infer formal Excel tables or propagate complex multi-row headers into every row.

### Retrieve retained pages and visual evidence

`tracecite page` reads retained PDF page text from the SQLite evidence database. Without a selector, it returns physical page 1. A selector can combine individual pages, closed ranges, and open ranges; overlapping terms are deduplicated, and pages return in ascending physical-page order.

```sh
tracecite page reports/example.pdf --database evidence.sqlite
tracecite page reports/example.pdf 5,12-15,20 --database evidence.sqlite
tracecite page reports/example.pdf 97- --database evidence.sqlite
tracecite page reports/example.pdf -20 --database evidence.sqlite
tracecite page reports/example.pdf all --database evidence.sqlite
```

Only the standalone selector `all` implicitly selects the complete source, and it cannot be combined with another term. Multi-page text output marks each physical page. A selected page with no extracted text, such as a scanned page synced without OCR, adds a note on stderr. `--format json` returns an ordered array of retained text, extraction metadata, a citation link, and validated paths for the indexed page render and figure crops. Search results expose the same page-render and figure-crop fields for page-local PDF matches.

`extract-pages` uses the same selector grammar but reads the indexed source PDF to create a derivative PDF and provenance manifest. The output directory must already exist outside the source root. TraceCite refuses stale source content, symlink output directories, overlap, and overwrite.

```sh
mkdir -p ../tracecite-exports
tracecite extract-pages reports/example.pdf 5,12-15,20 \
  --database evidence.sqlite \
  --output-dir ../tracecite-exports
```

Use database-backed text or indexed page assets for page-local questions. Select `all` only when the complete source is intentionally required.

### Verify quotations

`tracecite verify quote` checks a quotation against the retained text of one physical page, or of a contiguous page range such as `4-5` when the quotation continues across a page break:

```sh
tracecite verify quote reports/example.pdf 4-5 "Exact quotation" --database evidence.sqlite
```

- `exact`: the quotation occurs verbatim.
- `normalised`: the quotation matches after collapsing whitespace, straightening curly quotes and apostrophes, and ignoring case.
- `not-found`: neither matches; a changed word gives `not-found`.

The JSON result also reports `source_state` (`current`, `changed`, or `missing`), which compares the indexed version with the file under `--root` (default: the current directory). Verification always uses the indexed text. When the file changed, a warning on stderr asks for a re-sync.

### Build the documentation

```sh
uv run tracecite docs build docs
uv run tracecite docs build docs_quarto_py --only python
uv run tracecite docs build docs_quarto_jl --only julia
```

<!-- TODO:
Explain the expected `[WARNING] Could not fetch resource`
-->

The public builder discovers configured render inputs and automatically selects the complete site when both runtimes are available. If Julia is unavailable, it names every configured Julia source it skips and renders the Python overlay without modifying Julia sources. Use `--only python` or `--only julia` for explicit reduced builds. External projects that already have rendered and staged retained Markdown can invoke `tracecite prepare` directly after their Quarto render.

See `docs/examples/report-adoption/aemo-isp-comparison/` for a complete, real example of the author -> check -> index -> search -> doctor -> publish-only workflow using two AEMO Integrated System Plan reports.

`docs/examples/report-adoption/aemo-isp-comparison/docs/tracecite.toml` demonstrates the documentation evidence contract. Schema version 1 defines exactly `authored_root`, `retained_root`, `staged_root`, `source_links`, `index_output`, `publication_exclude`, and optional `host_render_command` under `[docs]`. Contract paths are repository-relative and must remain inside the repository.

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

The generated copy includes `_tracecite/tables.jsonl` and `_tracecite/manifest.json`. Its `_quarto.yml` is derived from the selected documentation profile; it keeps the theme and navigation and removes execution engines and build hooks. The copy is disposable, gitignored, and excluded from recursive ingestion.

The copied Markdown is deliberately redundant. It keeps the original table for audit and appends the normalised representation for inspection. Normal indexing can consume `tables.jsonl` or the `NormalisedTable` objects directly, without writing the copied site.

### Install the agent skills

TraceCite bundles three AI agent skills: `using-tracecite`, `writing-evidence-backed-reports`, and `routing-documentation-source-links`. Copy them into the project's `.agents/skills/` directory:

```sh
tracecite skills install
```

`--target` installs them into another skills directory, for example Claude Code's personal skills:

```sh
tracecite skills install --target ~/.claude/skills
```

Running the command again replaces the copies with the skills from the installed TraceCite version.

## Contributing

### Environment

The core package needs only Python.

```sh
uv venv
source .venv/bin/activate
uv pip install -e ".[evidence,test]"
```

`requirements.txt` pins the runtime and evidence dependencies to the latest versions that `pyproject.toml` allows. Install it for a reproducible environment, and refresh it with [`pru`](https://github.com/yasirroni/pru). Installing `-e ".[evidence]"` in the same command keeps the upgrades within the `pyproject.toml` bounds:

```sh
uv pip install -r requirements.txt
pru -r requirements.txt upgrade_requirements --cmd 'uv pip install --upgrade -e ".[evidence]"'
```

Building the whole `docs/` also needs the Julia environment:

```sh
julia --project=. -e 'using Pkg; Pkg.instantiate()'
```

### Lint and format

[pre-commit](https://pre-commit.com/) runs [Ruff](https://docs.astral.sh/ruff/) on the Python files and type-checks the whole project with [ty](https://github.com/astral-sh/ty) in each commit. Install it once and enable the hook:

```sh
uv tool install pre-commit
pre-commit install
```

To check every file, run `pre-commit run --all-files`. [Pyright](https://github.com/microsoft/pyright), the type checker behind Pylance, runs only on request with `pre-commit run --hook-stage manual pyright --all-files`.

### Test

Python tests and build:

```sh
python -m pytest
uv build
```

The Julia package is tested by its documentation example, `docs/examples/julia/dirty_dataframe.jl`. Building the documentation runs the example, including its hidden checks:

```sh
tracecite docs build docs
```
