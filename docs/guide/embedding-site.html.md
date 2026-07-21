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

The repository wrapper, `scripts/build_docs.py`, runs the first Quarto render, stages retained Markdown, invokes `tracecite prepare`, and checks retained-Markdown freshness. It selects the Python or Julia profile and coordinates the optional second render; normalisation remains in the public CLI and package. Run it through the project environment so the installed console script is available:

```bash
uv run scripts/build_docs.py
uv run scripts/build_docs.py --tracecite /path/to/tracecite
```

Projects using a different build system can run the public `tracecite prepare` command directly after Quarto has produced retained Markdown.

The ranked-results tutorial shows the public API and CLI mapping that produces
this inspection source: [Normalise and inspect ranked results](../examples/python/hottest_temperature.py).

```bash
tracecite prepare docs/build \
  --project-config docs/_quarto.yml \
  --project-profile python \
  --source-project docs \
  --keep-embedding-markdown .tracecite/embedding-site \
  --render-embedding-site
```

The second site is diagnostic. It is marked as generated, protected against accidental deletion of unrelated directories, and safe to rebuild at any time.
