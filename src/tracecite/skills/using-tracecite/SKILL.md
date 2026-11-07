---
name: using-tracecite
description: Use when local PDF, Markdown, or OOXML workbook sources must be synchronised into a TraceCite SQLite evidence database, searched lexically and semantically, inspected through source-specific locators, pruned, or diagnosed. PDF-only operations also support selected pages, assets, derivative PDFs, quotation checks, and report verification. Requires explicit runtime paths or a profile. Do not use for source capture, report prose, or public-link routing.
---

# Using TraceCite

Sync local sources into a TraceCite SQLite database, then search, retrieve, verify, prune, and diagnose them.

## Scope

Use this skill once the sources are on disk. Do not use it to find or download sources, to write report prose (`writing-evidence-backed-reports`), or to swap local and public links (`routing-documentation-source-links`).

Supported sources are `.pdf`, `.md`, `.xlsx`, and `.xlsm`. Legacy `.xls` is not supported. Workbook ingestion reads stored content only. It does not run VBA, recalculate formulae, refresh external data, or reproduce all Excel display formatting.

## Prerequisites

- The `tracecite` console script from an installed TraceCite package. This skill does not install it. `tracecite skills install [--target DIR]` copies the bundled skills into `.agents/skills/`.
- A profile (`--config`), or explicit `--root`, `--manifest`, `--database`, and `--model-cache-dir`. Manifests select sources with `[[source]] path`, `[[include]] glob`, and `[[exclude]] glob` rules.
- The caller owns the database and model-cache paths.

## Procedure

1. **Check the runtime.** Run `tracecite --help` and confirm that the profile or source root, manifest, database, and model cache exist. If one is missing, stop and name it; do not invent a database path. Do not run a source entry module or import from an unrelated checkout in place of the installed script.
2. **Sync.**
   ```bash
   tracecite sync --config <config-path> [--json]
   tracecite sync path/inside/root.pdf --root <dir> --manifest <manifest.toml> --database <db> --model-cache-dir <cache>
   ```
   Sync is incremental and idempotent. It never deletes a source: a missing or unselected source stays indexed until an explicit prune. `--full` reparses every source, `--reembed` regenerates embeddings, and `--no-assets` skips PDF renders. Status `aborted-source-changed` means a source changed during the sync; run it again.
3. **Search, retrieve, and verify.**
   ```bash
   tracecite search "later coal retirement" --database <db> --limit 20 [--lexical-only] [--source-type pdf]
   tracecite page path/to/source.pdf 63-66 --database <db> [--format json]
   tracecite extract-pages path/to/source.pdf 63-66 --output-dir <dir> --database <db>
   tracecite verify quote path/to/source.pdf 65 "Exact quotation" --database <db>
   tracecite verify report docs/reports/<report>.md --root <dir> --database <db> [--source-links docs/source-links.toml --source-links-root <dir>]
   tracecite doctor --database <db>
   ```
   Search accepts FTS5 syntax: quoted phrases, `OR`, `NOT`, and prefixes such as `retire*`. Quote the shell argument. If FTS5 cannot parse the query (`de-rating`, `10%`, an unbalanced quote), lexical search matches every word instead and says so on stderr, so stdout stays valid JSON. `--lexical-only` skips loading the embedding model.
4. **Turn results into evidence.**
   - Rank and `fused_score` find candidates; they are not proof. Check `source_path`, `source_type`, and `source_sha256` before you assume a hit is from the intended source or year. Narrow a mixed corpus with more specific wording or `--source-type`. A Markdown hit can locate a claim but is not external-source proof.
   - Read the full physical page with `tracecite page`. Read the neighbouring pages when the claim depends on a table, figure, footnote, or continuation. Selectors are `65`, `63-66`, `63-`, `-66`, comma-separated combinations, or `all` on its own; an omitted selector means page 1. Use `--format json` to get page renders and figure crops when layout matters.
   - Do not open the whole source PDF for a page-local question; use `all` only when you mean the whole source. Use `extract-pages` only when a tool needs PDF input, with an existing output directory outside the source root.
   - Before you quote, run `verify quote` on the physical page. `exact` matches the retained text. `normalised` is acceptable only when the wording is exact after whitespace, curly-quote, and case normalisation. `not-found` is not verification; never report it as verified. When sources conflict, keep the evidence from each and state the limitation.
   - Cite `<source-path>#page=<N>` with the physical page, which can differ from the printed page label. Use an official publisher URL when the documentation's public-link policy gives one; otherwise label the link as local.
   - For a workbook hit, check `locator.sheet` and `locator.exact_ranges` in the workbook. `locator.range` is a bounding rectangle and can include cells that did not contribute. `page`, `extract-pages`, `verify quote`, and PDF assets do not apply to workbooks.
5. **Prune only on explicit request.** `tracecite prune ...` without `--apply` only previews; run it first. A normal prune needs a positive `[[source]]` or `[[include]]` selector and the source root (`--root` or the profile). Excludes only narrow the selection, and a selection with no matches is rejected. The plan covers unselected sources and selected sources whose files are gone. Use `--all` only when the user means to remove every source. Only `--apply` commits. Exit status `3` means the prune committed but file or compaction cleanup is incomplete.
6. **Run `doctor`** after a bulk sync, a restore, or suspected corruption. Database, vector, asset, or hash issues block until resolved. `WARNING` lines about sources that changed or disappeared on disk are not integrity issues; the indexed text stays citable.

## Rules

- Evidence identity is the normalised root-relative path plus a page or line. Workbook evidence adds the source SHA-256, the worksheet, and the exact A1 ranges. Do not invent other IDs.
- Never change source files, and never let verification rewrite maintained Markdown.
- Keep `extract-pages` output outside the source root; it is disposable and must not be synced.
- Never commit databases, model caches, SQLite sidecars, PDF renders or crops, or other runtime output.

## References

Load a reference only when the task needs it:

- `references/retrieval.md`: search fusion, result fields, and query recovery. Read it to interpret search output.
- `references/pdf-and-assets.md`: page selection, `extract-pages`, quotation and report verification statuses, and assets.
- `references/schema-and-migrations.md`: manifest format, evidence identity, and stored tables.
- `references/synchronisation.md`: invalidation, renames, and the sync transaction. Read it when a sync result looks wrong.
- `references/architecture.md`: module layout and design limits. Read it before you change TraceCite itself.
