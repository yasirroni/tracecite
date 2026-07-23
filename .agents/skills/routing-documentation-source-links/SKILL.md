---
name: routing-documentation-source-links
description: Use when one maintained Markdown documentation tree must keep local source-PDF links for repository use while a generated public build substitutes official publisher URLs. Applies to source-link registries, safe rewriting of reference definitions and narrow inline PDF links, staged Documenter or static-site builds, and local/public validation. Do not use for source capture, indexing, quotation verification, or report prose.
---

# Routing Documentation Source Links

Maintain one Markdown authority. Route only the generated build copy to a local or public destination according to a compact source registry.

## Ownership and hand-offs

- `using-tracecite` owns the path/page verifier contract this skill consumes: local corpus paths, extraction, search, and report verification remain there.
- `writing-evidence-backed-reports` owns the complementary report-writing workflow: report prose, evidence interpretation, and local descriptive citations remain there.
- This skill owns `docs/source-links.toml`, target-specific staging, conservative link substitution, and documentation-build integration.
- Do not download sources, parse PDFs, generate embeddings, interpret report evidence, or rewrite maintained Markdown in place.

## Required architecture

This skill is the control-plane contract for the companion Julia implementation normally placed under `tools/doc-link-routing/`. Installing the skill ZIP alone does not patch a host repository or create that tool project.

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
local PDF paths        official HTTPS URLs
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
2. **Confirm stable source paths.** Every routed source path must match a normalised local path used by TraceCite and the maintained report's reference definitions or narrow inline PDF links.
3. **Create or validate `source-links.toml`.** Use the schema in `references/registry-contract.md`; do not store quotations, page evidence, vectors, or report claims in it.
4. **Stage atomically.** Copy the maintained source tree into a fresh temporary sibling, apply target-specific changes there, validate it, then atomically replace the previous staging tree. Preserve the previous valid staging tree on failure.
5. **Rewrite conservatively.** Process only recognised Markdown reference definitions and the narrow inline form `[descriptive text](relative/path.pdf#page=N)` outside protected Markdown regions. Preserve labels, query strings, fragments, and all unrelated text. See `references/staging-and-rewriting.md`.
6. **Select the target explicitly.** Default to `local`; allow only `local` or `public`. A public build substitutes `public_url` and appends the existing `#page=N` fragment after any URL query string.
7. **Integrate at the documentation-build boundary.** In Documenter.jl, stage inside `make.jl` before `makedocs`; do not alter Literate generation. See `references/documenter-integration.md`.
8. **Validate before build.** Apply target-specific path, URL, duplicate-path, ambiguity, and no-mutation checks. See `references/validation-and-failure-modes.md`.
9. **Build from the staged source.** Upload only generated HTML/assets intended for publication. Never include local PDFs, `tracecite.sqlite`, embedding caches, source-capture workspaces, or private evidence.
10. **Reconcile the verifier contract.** TraceCite report verification and the routing implementation must parse the same schema-v2 `[[source]]` registry keyed by `local_path`. Patch existing readers rather than creating a second parser, then rerun the relevant tests.

Expected companion-tool paths:

```text
tools/doc-link-routing/src/source_links.jl
tools/doc-link-routing/test/runtests.jl
```

Run its fixture suite with:

```sh
julia --project=tools/doc-link-routing tools/doc-link-routing/test/runtests.jl
```

## Final registry shape

```toml
schema_version = 2

[[source]]
title = "2026 Integrated System Plan"
publisher = "Australian Energy Market Operator"
local_path = "sources/aemo/2026-integrated-system-plan-isp.pdf"
public_url = "https://www.aemo.com.au/path/report.pdf?rev=...&sc_lang=en"
public_origin = "official"
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

Because Markdown support varies between host renderers, each host integration
must include a renderer pressure test that asserts an actual HTML anchor for
the maintained syntax it selects; this skill does not claim either form is
universally rendered by every Documenter configuration.

## Documenter boundary

For Documenter.jl sites, run routing after any maintained/generated Markdown has been produced and before `makedocs(source = ...)` reads the source tree. Keep route selection explicit, stage into a generated source tree, and preserve the host site's existing navigation/page-registry authority.

## Stopping conditions

Stop without replacing the current valid staging tree when:

- the registry is malformed, duplicated, ambiguous, or unsafe;
- a cited local path has no unique source entry;
- a public target lacks an official HTTPS URL;
- the page fragment is malformed or non-positive;
- rewriting would touch fenced code, raw blocks, arbitrary inline prose, or maintained Markdown;
- the host build lifecycle or target branch cannot be established.

## References

- `references/registry-contract.md` — schema-v2 fields, path and URL rules, and path-based reconciliation.
- `references/staging-and-rewriting.md` — atomic staging, conservative Markdown parsing, target transformation, and idempotence.
- `references/documenter-integration.md` — generic Julia/Documenter integration pattern.
- `references/validation-and-failure-modes.md` — required tests, diagnostics, safety checks, and deployment exclusions.
