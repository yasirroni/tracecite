---
name: using-tracecite
description: Use when local PDF, Markdown, or OOXML workbook sources must be synchronised into a TraceCite SQLite evidence database, searched lexically and semantically, inspected through source-specific locators, pruned, or diagnosed. PDF-only operations also support selected pages, assets, derivative PDFs, quotation checks, and report verification. Requires explicit runtime paths or a profile. Do not use for source capture, report prose, or public-link routing.
---

# Using TraceCite

Synchronise an explicit local corpus into a TraceCite database with FTS5 lexical search, sqlite-vec semantic search, retained PDF-page, Markdown-line, and workbook sheet/A1 locators, generated PDF assets, quotation verification, report verification, explicit pruning, and `doctor` diagnostics.

## When to use

Use this skill once source files already exist on disk and an agent needs to:

- sync configured `.pdf`, `.md`, `.xlsx`, and `.xlsm` sources without auto-pruning unavailable content;
- search by wording and semantic similarity;
- retrieve PDF evidence by normalised root-relative path plus selected physical pages;
- inspect workbook evidence through its source SHA-256, worksheet, bounding range, and exact A1 ranges;
- verify a quotation or a Markdown report against retained source text;
- inspect database/assets with `doctor` or run an explicit prune preview/apply.

Do not use this skill for discovering or downloading sources, writing report narrative (`writing-evidence-backed-reports` owns that), or substituting local/public documentation links (`routing-documentation-source-links` owns that). This skill owns TraceCite runtime use, path/page evidence identity, synchronisation, search, verification, pruning, and diagnostics.

## Prerequisites

- A TraceCite package and a Python environment that installs the `tracecite` console script. Installing this skill alone does not install the executable package.
- A source root containing one or more supported `.pdf`, `.md`, `.xlsx`, or `.xlsm` files.
- A combined TraceCite config with explicit inline `[[source]] path = ...`, `[[include]] glob = ...`, and optional `[[exclude]] glob = ...` rules. Separate `--manifest` inputs may augment those inline rules.
- A database path and model-cache path owned by the caller. Repository-neutral callers may choose any paths.

## Exact invocation

Prefer the installed console script:

```bash
tracecite <command> [--config PATH] [...]
```

When the package checkout and runtime environment differ, resolve them separately and use the environment that owns the runtime artifacts; do not rely on imports from a disposable checkout.

## Procedure

1. **Confirm runtime and inputs.** Verify `tracecite --help`, source root, manifests/profile, database path, and model-cache path. Do not invent separate public IDs. PDF and Markdown evidence use the normalised root-relative path plus their page or line locator. Workbook evidence additionally uses the indexed source SHA-256, worksheet, and exact A1 ranges.
2. **Sync the corpus:**
   ```bash
   tracecite sync --config <config-path>
   tracecite sync path/inside/root.pdf --root <dir> --manifest <manifest.toml> --database <db> --model-cache-dir <cache>
   ```
   Sync is incremental, idempotent, and non-pruning. Missing selected sources and indexed-but-unselected sources remain stored until explicit pruning.
3. **Search, retrieve, and verify:**
   ```bash
   tracecite search "later coal retirement" --database <db> --limit 20
   tracecite page path/to/source.pdf 65 --database <db>
   tracecite page path/to/source.pdf 63-66 --database <db>
   tracecite page path/to/source.pdf 63-66 --format json --database <db>
   tracecite extract-pages path/to/source.pdf 63-66 --output-dir <dir> --database <db>
   tracecite verify quote path/to/source.pdf 65 "Exact quotation" --database <db>
   tracecite verify report docs/reports/<report>.md --root <dir> --database <db> [--source-links docs/source-links.toml --source-links-root <dir>]
    tracecite doctor --database <db>
    ```
4. **Build evidence from retrieval results.** Treat search rank and fused score as candidate-discovery signals, not proof. Narrow a mixed corpus with more specific wording and by inspecting the returned `source_path`, `source_type`, and `source_sha256`; do not infer that a result is from the intended year or source merely because it ranked first. Markdown results can help locate a claim but are not external-source proof.

   For workbook results, inspect `locator.sheet` and `locator.exact_ranges` against the indexed workbook. `locator.range` is a bounding rectangle and may include cells that did not contribute to the passage. Use a workbook viewer for cell inspection; `tracecite page`, `extract-pages`, quotation verification, and PDF assets do not apply to workbook sources.

   For each candidate, retrieve the complete physical page with `tracecite page`. Omission selects physical page 1. Selectors accept positive pages, closed ranges (`63-66`), open ranges (`63-` or `-66`), and comma-separated combinations; overlapping terms are deduplicated in ascending physical-page order. The standalone selector `all` explicitly selects every indexed page and cannot be combined with another term.

   Inspect neighbouring pages when the claim depends on a table, figure, footnote, or continuation. When layout matters, use `tracecite page ... --format json` to locate the validated indexed page render and figure crops. If a PDF derivative is required by the inspection tool, use `tracecite extract-pages` with the same selector and an existing caller-owned output directory outside the source root. Do not open the complete source PDF for a page-local question; use `all` only when complete-source inspection is intentional.

   If a quotation is used, run `tracecite verify quote` against the physical page. `exact` means the quotation matches retained text; `normalised` is acceptable only when the quoted wording is exact after the tool's documented normalisation; `not-found` is not verification and must not be silently paraphrased as verified. Resolve conflicts by retaining the competing source/page evidence and stating the limitation.

   Construct the final link from the returned normalised `source_path` and physical page, for example `<source-path>#page=<N>`. Use an official publisher or agency URL when the documentation's public-link policy provides one; otherwise use the local source link and label its local scope. A physical PDF page may differ from the printed page label.
5. **Prune only on explicit request.** Run `tracecite prune ...` first as a preview. A normal prune must contain a positive `[[source]]` or `[[include]]` selector; excludes only narrow it, and a zero-match selection is rejected. Use `tracecite prune --all ...` only when the user explicitly intends to remove every indexed source. Only `tracecite prune --apply ...` may commit removals. Treat exit status `3` as a committed database prune with incomplete filesystem cleanup, not as an uncommitted failure.
6. **Run `doctor` after bulk syncs, restores, or suspected corruption.** Treat reported database, vector, asset, or hash issues as blocking until resolved.

### Query syntax and punctuation

The query is passed to both FTS5 `MATCH` and vector retrieval. Valid raw FTS5 expressions, including quoted phrases, boolean operators, and prefix expressions such as `retire*`, retain their normal lexical behaviour. Quote the shell argument when it contains spaces or FTS punctuation.

Ordinary prose containing punctuation that FTS5 rejects, such as `10%, 50%, and 90%`, does not abort hybrid retrieval. TraceCite reports the lexical fallback on stderr, retries lexical search with a quoted query, and sends the original text to vector retrieval. The fallback is only for the identified FTS5 syntax error; unrelated SQLite errors still propagate. Because diagnostics use stderr, `--json`-compatible search output remains valid JSON on stdout.

## Boundaries

- PDF, Markdown, `.xlsx`, and `.xlsm` OOXML workbooks are supported source formats. Legacy binary `.xls` is not supported.
- Workbook ingestion reads stored package content only. It does not execute VBA, recalculate formulae, refresh external data, or reproduce all Excel display formatting.
- Do not add old command/package compatibility aliases.
- Never mutate authoritative source files, and never let verification rewrite maintained Markdown.
- Keep selected-page derivatives outside the source root. They are disposable caller-owned runtime outputs and must not be synchronised automatically.
- Do not commit generated databases, embedding-model caches, SQLite sidecars, PDF renders/crops, or other runtime derivatives.
- Help commands must remain lightweight: they must not import or touch parsers, PDF/OCR, embeddings, sqlite-vec, manifests, databases, projects, caches, or network resources.

## References

- `references/architecture.md` — module layout, layering, and out-of-scope technology list.
- `references/schema-and-migrations.md` — current schema and path/page evidence contract.
- `references/synchronisation.md` — invalidation, retention, rename, transaction, and pruning behaviour.
- `references/retrieval.md` — hybrid FTS5/vector search design and result fields.
- `references/pdf-and-assets.md` — PDF page/chunk extraction, quotation verification, and asset semantics.
- `references/workspace-runtime.md` — Git worktree-safe path resolution and runtime setup.
