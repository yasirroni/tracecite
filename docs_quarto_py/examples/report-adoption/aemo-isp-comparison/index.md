---
title: "Evidence-backed AEMO report workflow"
---

This example shows how TraceCite supports a routine evidence-backed report from local authoring through a publish-only snapshot.
It uses the 2024 and 2026 Australian Energy Market Operator Integrated System Plans to demonstrate physical-page citations, local-to-public link routing, searchable indexing, diagnostics, and publication without the source PDFs or database.

[Read the published AEMO comparison](public/report.md).

## Workflow

Run the workflow from `docs/examples/report-adoption/aemo-isp-comparison/`:

```sh
python3 scripts/render_docs.py

uv run --project ../../../.. python -m tracecite docs author \
  --docs-config docs/tracecite.toml \
  --repo-root .

uv run --project ../../../.. python -m tracecite docs index \
  --docs-config docs/tracecite.toml \
  --repo-root .

uv run --project ../../../.. python -m tracecite docs search \
  "coal retirement Step Change" \
  --docs-config docs/tracecite.toml \
  --repo-root .

uv run --project ../../../.. python -m tracecite docs doctor \
  --docs-config docs/tracecite.toml \
  --repo-root .

uv run --project ../../../.. python -m tracecite docs check \
  --docs-config docs/tracecite.toml \
  --repo-root .

python3 scripts/update_public_snapshot.py
python3 -S scripts/publish_static.py /path/to/output
```

The sequence keeps each responsibility explicit:

1. `docs/authored/report.qmd` is the human-edited Quarto source.
2. `docs/retained/report.md` is generated evidence used for checking and indexing.
3. Local citations resolve to the PDFs under `sources/aemo/` during authoring and review.
4. `docs/source-links.toml` routes recognised PDF citations to official AEMO URLs for the public target.
5. `public/report.md` is the committed publish-only snapshot.
6. `.tracecite/` and `docs/.tracecite-stage/` remain disposable derived state.

## Evidence used in the comparison

The report cites physical page 10 of the 2024 ISP and physical pages 76-77 of the 2026 ISP.
The headline percentages use different fleet baselines, so Figure 18 of the 2026 ISP provides the direct edition-to-edition comparison on common capacity and time axes.

Search rank is used to find candidate evidence, not to prove the final interpretation.
The cited pages and Figure 18 must still be read in their source context before the report is published.

## Publication boundary

The publish-only script reads only `public/` and `static/`.
It does not require TraceCite, Quarto, the source PDFs, the vector database, the index-input mirror, or the embedding-model cache.
