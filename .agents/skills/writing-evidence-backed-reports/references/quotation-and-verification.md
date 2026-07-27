# Quotation and Verification Discipline

## Command usage

Use the exact invocation supplied by `using-tracecite` and the host repository's TraceCite installation:

```bash
tracecite sync --root <dir> --manifest <manifest.toml> --database <db> --model-cache-dir <cache>
tracecite search "later coal retirement" --limit 20 --database <db>
tracecite page <source-path> <physical-page> --database <db>
tracecite verify quote <source-path> <physical-page> "Exact quotation" --database <db>
tracecite verify report <report.md> --root <dir> --database <db> [--source-links <toml> --source-links-root <dir>]
tracecite doctor --database <db>
```

Use the installed `tracecite` console script from the active environment. Do not rely on imports from a disposable checkout.

## Quote states

| State | Meaning | Authoring action |
|---|---|---|
| `exact` | The submitted text matches retained page text exactly. | Quote may be used after source-page review. |
| `normalised` | It matches after controlled whitespace/hyphenation normalisation. | Quote may be used, but compare with the visible PDF page. |
| `not-found` | The verifier cannot establish the quotation. | Do not use it as an exact quotation. |

There is no `fuzzy` verifier state. Similarity search may help locate a passage, but it cannot verify exact wording.

## Batch-verifier boundary

`tracecite verify report` checks reference definitions, source paths, local paths, indexed pages, and associated block quotations according to the shipped implementation. It does not establish that every analytical claim is supported.

Before acceptance, manually check:

1. every material factual claim has nearby evidence;
2. every inference is labelled;
3. conflicts and date/scope differences are represented honestly;
4. tables and figures were visually reviewed;
5. no model-generated quotation entered the report without `tracecite verify quote`;
6. `doctor` reports no blocking source or index problem.

## Source-link compatibility

Use `--source-links` with the schema-v3 `[[source]]` registry owned by `routing-documentation-source-links`. Do not create a parallel registry merely to satisfy a verifier.
