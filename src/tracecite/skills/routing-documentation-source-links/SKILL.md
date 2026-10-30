---
name: routing-documentation-source-links
description: Use when one maintained Markdown documentation tree must keep local source-PDF links (or local-Markdown-to-public-HTML links) for repository use while a generated public build substitutes public destinations. Applies to source-link registries, safe rewriting of reference definitions and narrow inline PDF/Markdown links, staged Documenter or static-site builds, and local/public validation. Do not use for source capture, indexing, quotation verification, or report prose.
---

# Routing Documentation Source Links

Maintain one Markdown authority. Route only the generated build copy to a local or public destination according to a compact source registry.

## Ownership and hand-offs

- `using-tracecite` owns the path/page verifier contract this skill consumes: local corpus paths, extraction, search, and report verification remain there.
- `writing-evidence-backed-reports` owns the complementary report-writing workflow: report prose, evidence interpretation, and local descriptive citations remain there.
- This skill owns `docs/source-links.toml`, target-specific staging, conservative link substitution, and documentation-build integration.
- Do not download sources, parse PDFs, generate embeddings, interpret report evidence, or rewrite maintained Markdown in place.
- Do not grow this registry into a BibTeX/BibLaTeX/CSL export, a Zotero integration, or a DOI-resolution system. `metadata` is opaque routing-adjacent data, never a second bibliography store.
- TraceCite's Python implementation exposes the same operation as
  `tracecite.docs.stage_docs` and `tracecite docs stage --docs-config PATH
  --repo-root ROOT --target local|public`; the report verifier and staging use
  one schema-v3 registry and Markdown-link parser.

## Required architecture

`tracecite.docs.stage_docs` (CLI: `tracecite docs stage --docs-config PATH --repo-root ROOT --target local|public`) is the sole reference implementation of this contract. A host repository that needs this capability in a different runtime (e.g. a Julia/Documenter.jl package) vendors its own independent implementation of the schema-v3 registry and rewriting rules described here, rather than depending on `tracecite` directly.

```text
maintained Markdown with local links
            |
            v
source-links.toml + target selection
            |
            v
temporary staged Markdown tree
       /                   \
local target           public target
local PDF/Markdown     public destinations
       \                   /
          documentation builder
```

Authority boundaries:

```text
authoritative report Markdown   = docs/src/** or the repository's maintained source tree
authoritative routing metadata  = docs/source-links.toml
generated staging tree          = docs/.documenter-source/ or equivalent
generated site                  = docs/build/ or equivalent
```

## Workflow

1. **Inspect the host documentation lifecycle.** Identify maintained Markdown, generated Markdown, page/navigation registries, build scripts, staging directories, and deployment outputs. Do not assume one repository's Documenter layout matches another.
2. **Confirm stable source paths.** Every routed source path must match a normalised local `.pdf` or `.md` path used by TraceCite and the maintained report's reference definitions or narrow inline links.
3. **Create or validate `source-links.toml`.** Use the schema in `references/registry-contract.md`; do not store quotations, page evidence, vectors, or report claims in it. Arbitrary descriptive data belongs only in the opaque `metadata` table.
4. **Stage atomically.** Copy the maintained source tree into a fresh temporary sibling, apply target-specific changes there, validate it, then atomically replace only `staged_root/<target>`. Preserve the previous valid target, the other target, and unrelated siblings on failure.
5. **Rewrite conservatively.** Process only recognised Markdown reference definitions and narrow inline links: `[descriptive text](relative/path.pdf#page=N)` for PDF sources, and `[descriptive text](relative/path.md)` or `[descriptive text](relative/path.md#anchor)` for mapped Markdown sources, outside protected Markdown regions. Preserve labels, query strings, fragments, and all unrelated text. See `references/staging-and-rewriting.md`.
6. **Select the target explicitly.** Default to `local`; allow only `local` or `public`. A public build substitutes `public_url` and appends the existing `#page=N` (PDF) or `#anchor` (Markdown) fragment after any URL query string.
7. **Integrate at the documentation-build boundary.** In Documenter.jl, stage inside `make.jl` before `makedocs`; do not alter Literate generation. See `references/documenter-integration.md`.
8. **Validate before build.** Apply target-specific path, URL, duplicate-path, duplicate-name, ambiguity, and no-mutation checks. See `references/validation-and-failure-modes.md`.
9. **Build from the staged source.** Upload only generated HTML/assets intended for publication. Never include local PDFs, `tracecite.sqlite`, embedding caches, source-capture workspaces, or private evidence.
10. **Reconcile the verifier contract.** TraceCite report verification and the routing implementation must parse the same schema-v3 `[[source]]` registry keyed by `local_path` and the same narrow PDF `#page=N` / Markdown `#anchor` candidates. Patch existing readers rather than creating a second parser, then rerun the relevant tests.

## Final registry shape

```toml
schema_version = 3

[[source]]
name = "aemo-isp-2026"
local_path = "sources/aemo/2026-integrated-system-plan-isp.pdf"
public_url = "https://www.aemo.com.au/path/report.pdf?rev=...&sc_lang=en"

[source.metadata]
publisher = "Australian Energy Market Operator"
```

The Markdown page owns the physical page fragment:

```markdown
[aemo-2026-isp-p14]: ../../../sources/aemo/2026-integrated-system-plan-isp.pdf#page=14
```

The public staged form becomes:

```markdown
[aemo-2026-isp-p14]: https://www.aemo.com.au/path/report.pdf?rev=...&sc_lang=en#page=14
```

The same contract permits a non-image inline link when the host renderer does
not render reference usages:

```markdown
See [AEMO's 2026 Integrated System Plan, p. 14](../../../sources/aemo/2026-integrated-system-plan-isp.pdf#page=14).
```

Only a whitespace-free, repository-relative PDF destination with a positive
`#page=N` fragment is recognised. Inline links with titles, angle wrappers,
queries, unsafe or unmapped paths, images, autolinks, remote URLs, inline code,
raw HTML, and other unsupported syntax remain untouched or fail clearly when
they are malformed source-PDF candidates. Multiple recognised inline links on
one line are supported. Reference-definition support remains unchanged.

### Markdown-to-HTML routing

A local `.md` source registered in `source-links.toml` (for example a
maintained guide page, or a plain-Markdown evidence note kept outside the
retained documentation tree) can be linked to from other maintained Markdown:

```markdown
See the [searchable-evidence guide](../guide/searchable-evidence.md#anchor).

[guide]: ../guide/searchable-evidence.md
```

The public staged form substitutes the mapped `public_url` and preserves the
authored anchor, appended after any query string in `public_url`:

```markdown
See the [searchable-evidence guide](https://example.org/guide/searchable-evidence/#anchor).

[guide]: https://example.org/guide/searchable-evidence/
```

An anchor is optional; a bare `relative.md` destination routes to
`public_url` with no fragment appended. Unlike the PDF contract, an unmapped
or malformed local `.md` candidate (query-bearing, angle-wrapped, remote,
absolute, wrong-extension, or simply not present in the registry) is left
completely untouched rather than raising: most `.md` links are ordinary
documentation navigation, not source citations, so only a destination that
both parses as a narrow `relative.md`/`relative.md#anchor` candidate and
resolves to exactly one registered entry is rewritten. The public URL is
routing metadata an external client may fetch; this skill never fetches it,
parses HTML, or materialises rendered pages itself.

The Python staging contract uses the same exact registry fields (`name`,
`local_path`, `public_url`, optional `metadata`), allows only `local|public`
targets, and rewrites only `staged_root/<target>` from a fresh copy of
retained Markdown. The authored and retained trees are never modified.

Because Markdown support varies between host renderers, each host integration
must include a renderer pressure test that asserts an actual HTML anchor for
the maintained syntax it selects; this skill does not claim either form is
universally rendered by every Documenter configuration.

## Documenter boundary

For Documenter.jl sites, run routing after any maintained/generated Markdown has been produced and before `makedocs(source = ...)` reads the source tree. Keep route selection explicit, stage into a generated source tree, and preserve the host site's existing navigation/page-registry authority.

## Stopping conditions

Stop without replacing the current valid staging tree when:

- the registry is malformed, duplicated (by `name` or `local_path`), ambiguous, or unsafe;
- a cited local PDF path has no unique source entry;
- a public target lacks an HTTPS URL;
- the PDF page fragment is malformed or non-positive;
- rewriting would touch fenced code, raw blocks, arbitrary inline prose, or maintained Markdown;
- the host build lifecycle or target branch cannot be established.

An unmapped or malformed local Markdown candidate is not a stopping condition; leave it untouched (see `references/staging-and-rewriting.md`).

## References

- `references/registry-contract.md` — schema-v3 fields, opaque `metadata`, path and URL rules, and path-based reconciliation.
- `references/staging-and-rewriting.md` — atomic staging, conservative Markdown parsing, PDF and Markdown target transformation, and idempotence.
- `references/documenter-integration.md` — generic Julia/Documenter integration pattern.
- `references/validation-and-failure-modes.md` — required tests, diagnostics, safety checks, and deployment exclusions.
