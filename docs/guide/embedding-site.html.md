---
title: "Embedding inspection site"
---

The normal site must stay pure Quarto output. TraceCite therefore does not append retrieval records to `docs/build`.

`--keep-embedding-markdown` creates a separate, reproducible website source tree:

```text
docs/build/                         original Quarto output
    index.html
    python/hottest_temperature.html
    python/hottest_temperature.html.md

.tracecite/embedding-site/          generated inspection source
    _quarto.yml
    index.md
    python/hottest_temperature.md
    _tracecite/tables.jsonl
    _tracecite/manifest.json
    _site/                           optional second Quarto render
```

Each copied page contains the original table followed by a collapsible callout with the normalised representation. This makes transformation errors visible without polluting the human-facing source site or double-weighting the table in a normal indexing run.

The copied `_quarto.yml` is produced by merging the original base configuration with the selected profile. TraceCite preserves the site's theme, brand, navigation, and format settings, rewrites executable-page links from `.py` or `.jl` to copied `.md` pages, disables execution, and removes build hooks. The second Quarto run is therefore a presentation-only render of already executed knowledge.

```bash
tracecite prepare docs/build \
  --project-config docs/_quarto.yml \
  --project-profile python \
  --source-project docs \
  --keep-embedding-markdown .tracecite/embedding-site \
  --render-embedding-site
```

The second site is diagnostic. It is marked as generated, protected against accidental deletion of unrelated directories, and safe to rebuild at any time.
