---
name: writing-evidence-backed-reports
description: Use when verified passages from a local TraceCite evidence database must be turned into a natural research report, technical note, comparison, or blog post with exact quotations, descriptive path/page PDF citations, explicit inferences and limitations, and batch verification. Do not use for source capture, database synchronisation, or local/public documentation-link rewriting.
---

# Writing Evidence-Backed Reports

Write one maintained Markdown report per investigation. Use TraceCite to find candidate evidence, but treat the authoritative source files and reviewed PDF pages as the evidence.

## Ownership and hand-offs

- Hand off to `source-capture` before this skill when sources still need to be searched, downloaded, preserved, or catalogued.
- Load `using-tracecite` when the corpus must be synced, searched, inspected by page, quote-checked, report-verified, or checked with `doctor`; use its shipped CLI, not a second parser, store, vector search, hash checker, or verifier.
- Load `routing-documentation-source-links` after the maintained report is locally verified when local PDF reference definitions must become public URLs in a generated documentation build; use its schema-v3 `[[source]]` registry for `--source-links`.
- Do not create a YAML evidence registry, `docs/dense/`, a local/public report pair, or visible database-row citations.

## Prerequisites

- A working corpus-specific `tracecite.sqlite` and authoritative local source directory.
- The companion CLI and runtime described by `using-tracecite`.
- A target maintained Markdown path. In Documenter.jl projects, prefer `docs/src/reports/<report-id>.md`; otherwise use the repository's maintained documentation source tree.
- Stable reference definitions whose destination is the local source path plus a positive physical `#page=N` fragment; labels are opaque and need not encode the path.

## Workflow

1. **Resolve the exact CLI invocation.** Use the setup documented by `using-tracecite`; do not invent a second verifier.
2. **Search broadly.** Run lexical, semantic, or hybrid searches with several formulations. Retrieval rank identifies candidates, not proof.
3. **Inspect complete context.** Use `tracecite page <source-path> <physical-page>` and neighbouring pages where necessary. Open the original PDF page for tables, figures, layout-sensitive passages, or ambiguous reading order.
4. **Classify the intended statement.** Mark it internally as direct fact, exact quotation, synthesis, inference, conflict, limitation, or unsupported. Do not present inference as quoted fact.
5. **Verify exact quotations.** Run `tracecite verify quote`. Only `exact` and `normalised` are verified states. A merely similar or “fuzzy” passage is unverified and must not be quoted as exact text.
6. **Write the narrative.** Interleave evidence naturally with analysis. Keep quotations near the claims they support and use British English unless the repository specifies otherwise. See `references/report-structure.md`.
7. **Add local descriptive citations.** Use readable citation text and stable reference definitions that point to the local PDF with a positive physical `#page=N` fragment. See `references/reference-style-citations.md`.
8. **Handle figures conservatively.** Embed a checked local image derivative only when it helps the reader, and wrap it with the same source-page reference key. See `references/images-and-source-links.md`.
9. **Run batch verification.** Invoke `tracecite verify report <report.md> --root <dir> --database <db> [--source-links <toml> --source-links-root <dir>]`. The verifier checks only its implemented issue surface; apply the additional authoring checks in `references/quotation-and-verification.md` manually.
10. **Run `doctor`.** Source staleness and database integrity belong to `sync`/`doctor`, not report verification. Resolve blocking issues before publishing.
11. **Report gaps honestly.** If evidence remains insufficient, conflicting, inaccessible, or visually uncertain, say so in the report rather than filling the gap with model knowledge.

## Exact verifier contract

Use only the shipped commands:

```text
search
page
verify quote
verify report
doctor
```

`tracecite verify quote` returns:

```text
exact | normalised | not-found | structural-error
```

Only `exact` and `normalised` return process status `0`. Every other quotation
result is a failed evidence gate and returns non-zero. Machine-readable quote
results include the resolved `source_path`; report quote results also include
the paragraph-local `citation_key` that justified the check.

`tracecite verify report` citation issues are limited to:

```text
missing-definition
bad-local-path
path-outside-root
unindexed-path
bad-page
page-not-indexed
```

It does not independently detect duplicate or unused definitions, source-hash staleness, vector-composited figure crops, unsupported claims, or evidence that needs visual review. Treat those as authoring and review responsibilities; do not build a duplicate verifier inside this skill.

## Stopping conditions

Stop and report the limitation when:

- the source is absent, stale, or fails `doctor`;
- the relevant page is not indexed;
- a quotation returns `not-found`;
- the claim depends on a table or figure that has not been visually reviewed;
- two authoritative sources conflict and the report cannot resolve the conflict;
- the maintained Markdown path or citation convention is not established.

## References

- `references/report-structure.md` — narrative structure, claim classes, conflicts, limitations, and British-English voice.
- `references/reference-style-citations.md` — stable keys, local PDF destinations, visible references, and physical-versus-printed pages.
- `references/quotation-and-verification.md` — exact command contract, verifier limits, batch checks, and unsupported-claim discipline.
- `references/images-and-source-links.md` — page renders, figure crops, clickable images, and visual-review rules.
- `fixtures/` — synthetic redistributable reports and an executable validation path that creates a temporary corpus/database and runs the shipped verifier CLI.
