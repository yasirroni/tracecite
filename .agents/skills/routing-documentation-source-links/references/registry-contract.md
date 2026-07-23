# Source-Link Registry Contract

## Purpose

`docs/source-links.toml` routes one stable local source path to:

- the repository-local authoritative copy used for verification;
- the official public representation used by generated public documentation.

It is location metadata, not an evidence graph or bibliography database.

## Schema

```toml
schema_version = 2

[[source]]
title = "2026 Integrated System Plan"
publisher = "Australian Energy Market Operator"
local_path = "sources/aemo/2026-integrated-system-plan-isp.pdf"
public_url = "https://www.aemo.com.au/path/report.pdf?rev=...&sc_lang=en"
public_origin = "official"
```

Required fields:

| Field | Rule |
|---|---|
| `schema_version` | Integer `2`. |
| `title` | Human-readable document title. |
| `publisher` | Human-readable publisher or source organisation. |
| `local_path` | Normalised repository-relative path; no query or fragment. |
| `public_url` | Absolute official `https` URL; preserve required query parameters; no fragment. |
| `public_origin` | Use `official` for publisher-hosted sources; reject unknown values unless the schema is deliberately extended. |

Optional fields may include a local SHA-256 or an access-check timestamp, but they must not become a second editable copy of TraceCite evidence metadata.

## Identity and compatibility

- `local_path` must match the maintained report's reference-definition or narrow inline-link destination and the TraceCite database path after normalisation.
- Citation labels are opaque; the destination path and `#page=N` fragment carry authority.
- The TraceCite verifier must read this `[[source]]` shape when `--source-links` is supplied.
- Do not retain an old temporary registry shape as the publication authority; `local_path` is the routing key.

## Path rules

Reject:

- absolute local paths;
- `..` traversal that escapes the repository root;
- symlink resolution outside approved source roots;
- query strings or `#page=` fragments in `local_path`;
- duplicate normalised local paths unless a documented alias policy exists.

## URL rules

Reject:

- non-HTTPS publication URLs;
- credentials or secrets in URLs;
- `file:`, `javascript:`, or data URLs;
- a pre-existing fragment in `public_url`;
- mirrors when an official publisher URL is required.

Do not fetch every URL during each documentation build. Perform remote reachability and optional hash comparison in a separate scheduled check so publication does not depend on third-party availability.
