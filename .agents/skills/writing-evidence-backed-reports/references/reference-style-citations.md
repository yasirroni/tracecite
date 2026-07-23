# Reference-Style PDF Citations

## Opaque reference labels

Use reference-style Markdown definitions whose destination is the exact maintained local source path plus a positive physical PDF page fragment. The visible label is for Markdown linking only; it is not evidence identity, a page contract, or verifier authority.

Example:

```markdown
The 2026 ISP revises the development outlook [2026 ISP, report p. 10][source-a].

[source-a]: ../../../sources/aemo/2026-integrated-system-plan-isp.pdf#page=14
```

Rules:

- Reuse one definition for every citation to the same source page.
- Treat labels as opaque and freely renameable; do not encode page numbers, figure numbers, table numbers, or source identity into a required label shape.
- Resolve the path relative to the report file's directory.
- Use a repository-relative local path, never a private absolute path.
- Keep query strings and public URLs out of maintained report Markdown; `routing-documentation-source-links` owns public substitution.
- Use the physical PDF page in `#page=N`, even when the visible citation shows a different printed page label.

## Visible references section

Reference definitions do not normally render, so include a human-readable section:

```markdown
## References

- [AEMO, *2026 Integrated System Plan*, report p. 10][source-a]

[source-a]: ../../../sources/aemo/2026-integrated-system-plan-isp.pdf#page=14
```

## Citation placement

Attach the citation to the sentence, paragraph, quotation attribution, table note, or image it supports. Do not place a single citation at the end of a long section containing several independently checkable claims.

## Manual hygiene not covered by `tracecite verify report`

Check separately for:

- duplicate definitions with different destinations;
- definitions that are never used;
- two visible references that accidentally use different labels for the same source page;
- printed-page labels that contradict the document;
- links that escape the approved source directory.
