# Source-Link Registry Contract

## Purpose

`docs/source-links.toml` routes one stable local `.pdf` or `.md` source path to:

- the repository-local authoritative copy used for verification;
- the public representation used by generated public documentation.

It is location metadata, not an evidence graph or bibliography database. It does not replace BibTeX, BibLaTeX, CSL, Zotero, or DOI-resolution tooling, and it must not accumulate their responsibilities.

## Schema

```toml
schema_version = 3

[[source]]
name = "aemo-isp-2026"
local_path = "sources/aemo/2026-integrated-system-plan-isp.pdf"
public_url = "https://www.aemo.com.au/path/report.pdf?rev=...&sc_lang=en"

[source.metadata]
bibtex_id = "aemo2026isp"
publisher = "Australian Energy Market Operator"
type = "report"
```

The same contract routes a maintained local Markdown page to a public HTML destination:

```toml
[[source]]
name = "tracecite-searchable-evidence"
local_path = "docs/guide/searchable-evidence.md"
public_url = "https://example.org/guide/searchable-evidence/"

[source.metadata]
type = "documentation"
```

Required fields:

| Field | Rule |
|---|---|
| `schema_version` | Integer `3`. |
| `name` | Non-empty, unique, stable human/machine identifier. No bibliography-specific key syntax is imposed. |
| `local_path` | Normalised repository-relative path ending in `.pdf` or `.md`; no query or fragment; unique per registry (one `local_path` maps to one entry). |
| `public_url` | Absolute `https` URL; preserve required query parameters; no fragment, credentials, or user info. |

Optional field:

| Field | Rule |
|---|---|
| `metadata` | An optional `[source.metadata]` table. TraceCite preserves arbitrary keys and values opaquely: it does not interpret, normalise, export, or publish them, and assigns no behaviour to keys such as `bibtex_id`, `publisher`, or `type`. Do not treat `metadata` as a second editable copy of TraceCite evidence identity; it stays external to the evidence database. |

Reject any other source-level field (for example a misspelled `publc_url`) rather than silently absorbing it into metadata.

## Identity and compatibility

- `local_path` must match the maintained report's reference-definition or narrow inline-link destination and the TraceCite database path after normalisation.
- `name` is the stable identifier for the entry; citation labels in Markdown remain opaque, and the destination path plus `#page=N` fragment (PDF) or optional `#anchor` (Markdown) carry routing authority.
- The TraceCite verifier must read this `[[source]]` shape when `--source-links` is supplied.
- Do not retain an old schema-v2 (`title`/`publisher`/`public_origin`) or earlier registry shape as the publication authority; `local_path` is the routing key and schema v3 is the only accepted schema.

## Path rules

Reject:

- absolute local paths;
- `..` traversal that escapes the repository root;
- symlink resolution outside approved source roots;
- query strings or fragments in `local_path`;
- a `local_path` extension other than `.pdf` or `.md`;
- duplicate normalised local paths.

## URL rules

Reject:

- non-HTTPS publication URLs;
- credentials or secrets in URLs;
- `file:`, `javascript:`, or data URLs;
- a pre-existing fragment in `public_url`.

Query strings in `public_url` remain allowed; the router appends the authored PDF page or Markdown anchor fragment after any existing query string.

Do not fetch every URL during each documentation build. Perform remote reachability and optional hash comparison in a separate scheduled check so publication does not depend on third-party availability.
