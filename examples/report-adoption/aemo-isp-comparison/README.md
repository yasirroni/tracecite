# AEMO ISP Comparison Example

A small, real example demonstrating TraceCite's author → check → index → search → doctor → publish-only workflow using two editions of the Australian Energy Market Operator (AEMO) Integrated System Plan (ISP) report.

## Purpose

This example shows how TraceCite handles document evidence across a complete citation lifecycle: authors work with local PDFs and write evidence-backed content in Quarto Markdown, the check and index phases build and validate a searchable vector index, and the publish step distributes only a static snapshot with rewritten citations pointing to official public URLs. No source PDFs or search index travel with the published output.

## Sources

| Document | Publisher | Size | SHA-256 | Official URL |
|----------|-----------|------|---------|--------------|
| 2024 Integrated System Plan | Australian Energy Market Operator (AEMO) | 4340555 bytes | `f9cfa15b5bfb732939e4b67b05859c674749df0befd370c2937c2cdf14ab30d7` | https://www.aemo.com.au/-/media/files/major-publications/isp/2024/2024-integrated-system-plan-isp.pdf?la=en |
| 2026 Integrated System Plan | Australian Energy Market Operator (AEMO) | 7267935 bytes | `63729c0e74cdc7f2e2c3c895e511986f9efabf1696a99dfd5343f054659102e5` | https://www.aemo.com.au/-/media/files/major-publications/isp/2026/2026-integrated-system-plan-isp.pdf?rev=7f5dfd18aa1b4a3aab704c424f75afd3&sc_lang=en |

Both are also available on AEMO's general program page: https://www.aemo.com.au/energy-systems/major-publications/integrated-system-plan-isp

## Layout

```
.
├── _quarto.yml                          # Quarto project config; renders to gfm format
├── docs/
│   ├── tracecite.toml                   # TraceCite docs contract (schema_version 1)
│   ├── source-links.toml                # Maps local PDFs to official public URLs (schema_version 3)
│   ├── authored/
│   │   └── report.qmd                   # Authored Quarto report (human-edited source)
│   ├── retained/
│   │   ├── report.md                    # Generated retained Markdown input, tracked in git
│   │   └── .tracecite-manifest.json     # Generated freshness manifest, tracked in git
│   └── .tracecite-stage/                # Generated local/public staging & vector index (gitignored)
├── public/                              # Committed public snapshot (public-URL citations only)
├── sources/aemo/
│   ├── 2024-integrated-system-plan.pdf  # 2024 ISP report (Git LFS)
│   └── 2026-integrated-system-plan.pdf  # 2026 ISP report (Git LFS)
├── static/                              # Static assets for publish-only step
├── scripts/
│   ├── render_docs.py                   # Host-owned render hook; invoked by author mode
│   ├── update_public_snapshot.py        # Copies validated public staging to committed public/
│   └── publish_static.py                # Stdlib-only publish script; safe under python3 -S
└── README.md                            # This file
```

## Usage

Run these commands from the example's own directory (`examples/report-adoption/aemo-isp-comparison`).

1. `python3 scripts/render_docs.py`
   Render the authored report; done automatically by author mode below, shown for reference.

2. `uv run --project ../../../.. python -m tracecite docs author --docs-config docs/tracecite.toml --repo-root .`
   Author: render the authored report and stage local/public copies.

3. `uv run --project ../../../.. python -m tracecite docs check --docs-config docs/tracecite.toml --repo-root .`
   Check: read-only freshness verification of the staged output.

4. `uv run --project ../../../.. python -m tracecite docs index --docs-config docs/tracecite.toml --repo-root .`
   Index: build the searchable vector index.

5. `uv run --project ../../../.. python -m tracecite docs search "Integrated System Plan" --docs-config docs/tracecite.toml --repo-root .`
   Search the index.

6. `uv run --project ../../../.. python -m tracecite docs doctor --docs-config docs/tracecite.toml --repo-root .`
   Doctor: deeper integrity check.

7. `python3 scripts/update_public_snapshot.py`
   Copy validated public staging into the committed `public/` snapshot; refuses to run if check reports any problem.

8. `python3 -S scripts/publish_static.py /path/to/output`
   Publish-only: stdlib-only script (no TraceCite, no source PDFs) that copies only the committed `public/` and `static/` directories into an output directory.

## Citations in this Example

This example uses three kinds of citation:

1. **Local PDF citation with page number**: The 2024 ISP report is cited at a specific page. During authoring, this resolves to the local file in `sources/aemo/2024-integrated-system-plan.pdf`; in published output, it is rewritten to point to the official AEMO URL.

2. **Local PDF citation (2026 ISP)**: Similarly, the 2026 ISP report is cited with page precision, resolving locally and rewritten in published output.

3. **Plain website citation**: The general AEMO ISP program page (https://www.aemo.com.au/energy-systems/major-publications/integrated-system-plan-isp) has no local file and is never rewritten; it appears unchanged in both authored and published output.

## Requirements

- Quarto
- Git LFS
- Python 3.11+
- For author, check, and publish-only: standard TraceCite
- For index, search, and doctor: `tracecite[evidence]` extra
