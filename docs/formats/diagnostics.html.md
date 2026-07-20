---
title: "Structural diagnostics"
---

TraceCite stores diagnostics separately from factual retrieval text. Warnings therefore remain searchable for audits without being presented as the primary answer.

## Mixed-unit example

| Rank | Place | Maximum temperature (°C) |
|---:|---|---:|
| 1 | Example A | 323.85 K |
| 2 | Example B | 50.5 °C |

: A deliberately inconsistent unit example used to demonstrate diagnostics. {#tbl-mixed-unit-diagnostic}

The normaliser emits both `table.unit-conflict` and `table.mixed-units`. It does not convert either value automatically.

## Other checks

- duplicate and non-monotonic ordinal columns;
- duplicate rows and headers;
- missing configured row identity columns;
- explicit ordering inconsistent with row order;
- unsupported nested tables;
- cell spans and footer flattening;
- empty tables and generated fallback headers.

## Failure preservation

Default document ingestion does not discard a table merely because optional metadata or structure is malformed. TraceCite preserves the exact raw source, marks the result as unsupported, records `table.normalisation-failed`, and emits no retrieval text for that table. A later agent can still inspect the original evidence.

Strict validation deliberately fails instead:

```bash
tracecite check docs/build
```

For example, this invalid metadata is shown as source text rather than interpreted by this page:

````markdown
<!-- tracecite-table: {not-json} -->
| A | B |
|---|---|
| 1 | 2 |

: Broken metadata. {#tbl-broken}
````
