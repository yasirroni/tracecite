# TraceCite

TraceCite lets people and AI agents search their documents, cite the exact page or cell, and check that a quote matches its source.

Its core is source-linked table normalisation. Tables in rendered Python or Julia documentation stay unchanged as the original evidence, and TraceCite derives deterministic, self-describing row text from them for search.

TraceCite also indexes Markdown, PDF, `.xlsx`, and `.xlsm` files. It stores retained text, source hashes, full-text and vector search records, and locators (PDF pages, Markdown lines, and worksheet ranges), and verifies quotations and report citations against them.

`tracecite docs index` adds a project's retained documentation and its normalised tables to an evidence index. `tracecite docs stage` routes source links to local files or public URLs.

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

The normal site is pure Quarto output. The inspection copy, which doubles each table, is generated only on request.

`tracecite docs build docs` discovers configured executable inputs, builds the complete site when both runtimes are available or falls back to the available one with a warning naming each skipped file, stages retained Markdown, and optionally renders the inspection site. `tracecite prepare` does the table normalisation.

The evidence path is separate from the documentation renderer:

```text
declared PDF, Markdown, or workbook sources
    -> retained source extraction
    -> locator-aware chunks
    -> SQLite FTS5 and sqlite-vec
    -> ranked JSON results with source identity and evidence locators
```

## Prerequisites

- Python 3.11 or newer;
- Pandoc, standalone or bundled with Quarto;
- Quarto for documentation-site renders;
- Julia 1.10 or newer, only for Julia documentation pages.

The Python normaliser and CLI work without Julia. Automatic builds fall back to the Python overlay when configured Julia inputs cannot run; `--only julia` builds need Julia.

Install TraceCite from PyPI. Evidence synchronisation and hybrid search need the `evidence` extra; Quarto documentation builds with Python pages also need the `docs` extra:

```sh
pip install "tracecite[evidence]"
pip install "tracecite[evidence,docs]"
```

The `evidence` extra installs PyTorch through `sentence-transformers`. On Linux, pip installs the CUDA build by default, a download of several gigabytes. On a machine without a GPU, install the CPU build first:

```sh
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Workbook parsing reads OOXML packages with only the Python standard library, without Excel, Julia, Quarto, or third-party workbook readers.

## Usage

The `tracecite` CLI normalises tables and documents, builds documentation, and syncs and searches source evidence. `prepare` reads retained Markdown after a Quarto render and creates the optional inspection copy.

### Public API

```python
from tracecite.tables import (
    normalise_pandoc_table,
    normalise_html_table,
    normalise_document_tables,
)
```

`normalise_pandoc_table()` is the core contract. It accepts one Pandoc table and returns raw evidence, canonical Markdown, normalised text, row records, diagnostics, hashes, and version metadata.

Each row gets a deterministic `row_id`, which follows the logical row rather than its rank or position when `row_identity` metadata is supplied.

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

List sources in a manifest by explicit path or by include and exclude globs over `.pdf`, `.md`, `.xlsx`, and `.xlsm` files.

```toml
schema_version = 1

[[source]]
path = "2023-iasr-ev-workbook.xlsx"
```

Sync the sources into a database, search it lexically and semantically, then check its integrity:

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

- `sync` needs at least one `[[source]]` or `[[include]]` rule; without one, it stops without creating or changing the database.
- It prints one line per added, reparsed, renamed, missing, or unselected path; `--json` prints the full report.
- A declared `[[source]]` missing under the root is listed under `missing-sources`. A selected file that sync cannot read or parse, or that is a symlink, is listed under `skipped` with the reason; a skipped file indexed earlier keeps its previous rows. Either case ends with `status: incomplete` and exit 1, and the other sources still sync. A sync of one path checks only that path.
- A second `sync` or `prune --apply` of the same database waits for the first to finish.
- PDF pages without text, such as blank or scanned pages, are listed under `pages-without-text` when they are parsed, and `doctor` counts them on every run. Scanned pages need [Tesseract](https://github.com/tesseract-ocr/tesseract) for OCR; without it, sync stores those pages without text. After installing it, run `tracecite sync --full` to extract their text.
- `sync` is incremental and non-pruning. Sources that are gone or no longer selected stay searchable and citable until you preview and apply `tracecite prune`.

#### Prune

`prune` needs the source root (`--root` or a profile). It targets indexed sources the rules no longer select or whose file is gone from the root; the preview lists the latter under `missing_paths`. `--all` targets every indexed source and needs no root. `prune --apply` also compacts the database file.

#### Doctor

`doctor` warns about PDF pages without text, and with `--root <dir>` about sources that changed or disappeared since the last sync. Only database, vector, and asset integrity issues change its exit status; the last line counts the warnings.

#### Search

`search --source-type` (`pdf`, `markdown`, or `workbook`; repeatable) filters lexical and vector candidates before ranking and the `--limit` cut, not after:

```sh
tracecite search "coal retirement" \
  --database .tracecite/evidence.sqlite \
  --source-type pdf
```

- An empty query exits with status 2.
- `--lexical-only` uses full-text search alone and skips loading the embedding model.
- Chinese, Japanese, and Korean (CJK) text has no spaces, so lexical search also matches each CJK run of the query as a substring of the indexed text. This reads every passage, so it is slower than ordinary full-text search on a large database.
- The embedding model is English-only, so a query with CJK text skips vector search and uses lexical search only.
- Byte-identical files at different paths give one hit, under the shortest path (then the first in sort order), with the others in `duplicate_paths`.

Each result includes retrieval provenance and a source-specific locator. This abbreviated workbook result shows the stable fields; the worksheet and ranges vary with the workbook and chunk settings:

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

The path and SHA-256 identify the workbook version, and the worksheet and `exact_ranges` identify the passage's cells. `range` is only the bounding rectangle and can include other cells. Rank only marks candidate evidence, so inspect the returned cells before citing a result.

A portable workbook citation is the path, SHA-256, worksheet, and A1 ranges. Opening the exact range needs a workbook viewer or a separate provider-specific link.

#### Workbook boundaries

- The parser supports `.xlsx` and `.xlsm` OOXML packages, not legacy binary `.xls`.
- It keeps stored text, numeric, Boolean, error, formula, and cached formula values. Cached values reflect the workbook's stored state; formulae are not recalculated.
- It reads stored package content only and does not run VBA or refresh external links, Power Query, pivot caches, or data connections.
- It ignores style-only empty cells and does not reconstruct display formatting, so styled dates and times can stay numeric serials.
- It chunks workbooks by row and does not yet infer formal Excel tables or carry complex multi-row headers into every row.

### Retrieve retained pages and visual evidence

`tracecite page` prints retained PDF page text from the SQLite evidence database, physical page 1 by default. Selectors combine pages and closed or open ranges; overlaps are merged and pages come back in ascending physical order.

```sh
tracecite page reports/example.pdf --database evidence.sqlite
tracecite page reports/example.pdf 5,12-15,20 --database evidence.sqlite
tracecite page reports/example.pdf 97- --database evidence.sqlite
tracecite page reports/example.pdf -20 --database evidence.sqlite
tracecite page reports/example.pdf all --database evidence.sqlite
```

Only `all` implicitly selects the whole source, and it must stand alone. Multi-page text output marks each physical page, and a page with no text, such as a scanned page synced without OCR, adds a note on stderr. `--format json` returns an ordered array of retained text, extraction metadata, a citation link, and validated paths to the indexed page render and figure crops. Search results carry the same render and crop fields for page-local PDF matches.

`extract-pages` takes the same selectors and writes a derivative PDF and provenance manifest from the indexed source PDF. The output directory must already exist outside the source root; stale sources, symlinked output directories, overlap, and overwrites are refused.

```sh
mkdir -p ../tracecite-exports
tracecite extract-pages reports/example.pdf 5,12-15,20 \
  --database evidence.sqlite \
  --output-dir ../tracecite-exports
```

Answer page-local questions from database text or indexed page assets; select `all` only when you need the whole source.

### Verify quotations

`tracecite verify quote` checks a quotation against the retained text of one physical page, or a contiguous range such as `4-5` for a quotation that crosses a page break:

```sh
tracecite verify quote reports/example.pdf 4-5 "Exact quotation" --database evidence.sqlite
```

- `exact`: the quotation occurs verbatim.
- `normalised`: matches after collapsing whitespace, straightening curly quotes and apostrophes, and ignoring case.
- `not-found`: anything else, including one changed word.
- `page-not-indexed` or `source-not-indexed`: the page range or the source is not in the database; these exit 2, other failures exit 1.

The JSON also reports `source_state` (`current`, `changed`, or `missing`), which compares the indexed version with the file under `--root` (default: the current directory). Verification always uses the indexed text and warns on stderr to re-sync if the file changed.

### Build the documentation

```sh
uv run tracecite docs build docs
uv run tracecite docs build docs_quarto_py --only python
uv run tracecite docs build docs_quarto_jl --only julia
```

<!-- TODO:
Explain the expected `[WARNING] Could not fetch resource`
-->

Without Julia, the builder names each Julia source it skips and renders the Python overlay, leaving Julia sources untouched. `--only python` or `--only julia` builds one language. Projects with their own Quarto render can run `tracecite prepare` on their staged retained Markdown.

`docs/examples/report-adoption/aemo-isp-comparison/` is a complete author -> check -> index -> search -> doctor -> publish-only example using two AEMO Integrated System Plan reports.

`docs/examples/report-adoption/aemo-isp-comparison/docs/tracecite.toml` demonstrates the documentation evidence contract. Schema version 1 defines exactly `authored_root`, `retained_root`, `staged_root`, `source_links`, `index_output`, `publication_exclude`, and optional `host_render_command` under `[docs]`. Contract paths are repository-relative and stay inside the repository.

Open the built site:

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

The copy includes `_tracecite/tables.jsonl` and `_tracecite/manifest.json`, and its `_quarto.yml` keeps the selected profile's theme and navigation without execution engines or build hooks. It is disposable, gitignored, and excluded from recursive ingestion.

Its Markdown keeps each original table for audit and appends the normalised form for inspection. Normal indexing reads `tables.jsonl` or `NormalisedTable` objects directly and needs no copy.

### Install the agent skills

TraceCite bundles three AI agent skills: `using-tracecite`, `writing-evidence-backed-reports`, and `routing-documentation-source-links`. Copy them into the project's `.agents/skills/` directory:

```sh
tracecite skills install
```

`--target` picks another directory, such as Claude Code's personal skills:

```sh
tracecite skills install --target ~/.claude/skills
```

Rerunning it replaces the copies with the installed version's skills.

## Contributing

### Environment

The core package needs only Python.

```sh
uv venv
source .venv/bin/activate
uv pip install -e ".[docs,evidence,test]"
```

`requirements.txt` pins runtime and evidence dependencies to the newest versions `pyproject.toml` allows; install it for a reproducible environment. Refresh it with [`pru`](https://github.com/yasirroni/pru); installing `-e ".[evidence]"` in the same command keeps upgrades within `pyproject.toml` bounds:

```sh
uv pip install -r requirements.txt
pru -r requirements.txt upgrade_requirements --cmd 'uv pip install --upgrade -e ".[evidence]"'
```

Building the whole `docs/` also needs the Julia environment:

```sh
julia --project=. -e 'using Pkg; Pkg.instantiate()'
```

### Lint and format

On each commit, [pre-commit](https://pre-commit.com/) runs [Ruff](https://docs.astral.sh/ruff/) on changed Python files and [ty](https://github.com/astral-sh/ty) on the whole project. Install it once and enable the hook:

```sh
uv tool install pre-commit
pre-commit install
```

`pre-commit run --all-files` checks every file. [Pyright](https://github.com/microsoft/pyright), the checker behind Pylance, runs only on request with `pre-commit run --hook-stage manual pyright --all-files`.

### Test

Python tests and build:

```sh
python -m pytest
uv build
```

The Julia package is tested by `docs/examples/julia/dirty_dataframe.jl`, which the documentation build runs with its hidden checks:

```sh
tracecite docs build docs
```
