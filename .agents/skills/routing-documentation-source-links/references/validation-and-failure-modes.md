# Validation and Failure Modes

## Required fixture coverage

Test both targets with fixtures covering:

- a valid local PDF definition;
- an official URL containing a query string;
- a positive physical page fragment;
- repeated use of one reference definition;
- multiple reports referencing the same source;
- fenced-code and Documenter raw-block examples that remain byte-identical;
- malformed, missing, duplicate, and ambiguous mappings;
- path traversal and absolute-path rejection;
- public URL scheme and fragment rejection;
- atomic staging failure that preserves the previous valid tree;
- idempotent repeated builds;
- no mutation of maintained Markdown.
- multiple inline PDF links on one line;
- positive and malformed inline page fragments, query strings, titles, images,
  autolinks, inline code, escaped syntax, and nested file-relative paths;
- a host-renderer pressure test that checks the selected maintained syntax
  produces an actual HTML anchor.

## Cross-system validation

After adopting the final registry:

1. patch the existing TraceCite source-link reader rather than creating a second verifier;
2. rerun the complete TraceCite test suite;
3. update its skill references that mention the placeholder schema;
4. re-audit and repackage `using-tracecite`;
5. build reporting fixtures against the final `[[source]]` schema.

## Build exclusions

The public deployment artifact must not contain:

```text
source PDFs
tracecite.sqlite
embedding-model caches
source-capture workspaces
private evidence
staging directories
local absolute paths
```

Upload only the generated static site and deliberately public assets.

## Diagnostics

Errors must identify:

- Markdown file and line;
- reference key or inline link text;
- parsed local destination and page fragment;
- expected source path;
- registry entries considered;
- target mode;
- corrective action.

Do not silently leave a local link in public output when routing was required. Conversely, do not turn an unmapped local file into a guessed public URL.
