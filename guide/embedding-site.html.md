---
title: "Embedding inspection site"
---

The normal site must stay pure Quarto output. TraceCite therefore does not append retrieval records to `docs/build`.

`--keep-embedding-markdown` creates a separate, reproducible website source tree:

```text
docs/build/                         original Quarto output
    index.html
    examples/python/hottest_temperature.html
    examples/python/hottest_temperature.html.md

.tracecite/embedding-site/          generated inspection source
    _quarto.yml
    index.md
    examples/python/hottest_temperature.md
    _tracecite/tables.jsonl
    _tracecite/manifest.json
    _site/                           optional second Quarto render
```

Each copied page contains the original table followed by a collapsible callout with the normalised retrieval text. This makes transformation errors visible without polluting the main documentation site or double-weighting the table in a normal indexing run. The inspection representation is text, not an embedding vector.

The copied `_quarto.yml` is produced by merging the original base configuration with the selected profile. TraceCite preserves the site's theme, brand, navigation, and format settings, rewrites executable-page links from `.py` or `.jl` to copied `.md` pages, disables execution, and removes build hooks. The second Quarto run is therefore a presentation-only render of already executed knowledge.

The public `tracecite docs build docs` command runs Quarto, stages retained Markdown, calls the inspection export, and optionally renders the second site. Use the public CLI for automatic, Python-only, and Julia-only builds:

```bash
uv run tracecite docs build docs
uv run tracecite docs build docs --only python
julia --version
uv run tracecite docs build docs --only julia
```

Projects using a different build system can run the public `tracecite prepare` command directly after Quarto has produced retained Markdown; that direct command remains available independently of the automatic builder.

The ranked-results tutorial in the Python-only build shows the public API and
CLI mapping that produces this inspection source:
`../examples/python/hottest_temperature.py`.

```bash
tracecite prepare docs/build \
  --project-config docs/_quarto.yml \
  --project-profile python \
  --source-project docs \
  --keep-embedding-markdown .tracecite/embedding-site \
  --render-embedding-site
```

The second site is diagnostic. It is marked as generated, protected against accidental deletion of unrelated directories, and safe to rebuild at any time.
