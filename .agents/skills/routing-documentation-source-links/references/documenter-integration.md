# Documenter.jl Integration

## General boundary

Add routing after all maintained/generated Markdown sources exist and before `Documenter.makedocs` reads them.

```text
source generation -> target-specific staging -> makedocs -> generated site
```

Do not place publication routing inside analysis notebooks or Literate source generation.

## Documenter lifecycle template

In a typical Documenter workflow:

```sh
julia --project=docs -e 'using Pkg; Pkg.instantiate()'
julia --project=docs docs/render_literate.jl
julia --project=docs docs/make.jl
open docs/build/index.html
```

Preserve these responsibilities:

- source generation, if any, creates maintained Markdown before routing begins;
- `make.jl` or the equivalent build driver reads a source tree, computes navigation, and runs Documenter;
- composition scripts should remain thin wrappers around generation and build steps;
- existing page registries, navigation functions, page kinds, statuses, data-layer labels, and ordering fields remain the host repository's navigation authority.

## Template target selection

The following target selection and staging pattern is a generic template to re-verify against the host repository before `makedocs`.

```julia
const LINK_TARGET = lowercase(strip(get(ENV, "DOCS_LINK_TARGET", "local")))
LINK_TARGET in ("local", "public") ||
    error("DOCS_LINK_TARGET must be local or public")
```

Use a sibling staging tree such as:

```text
docs/src/                  maintained
docs/.documenter-source/  generated staging
docs/build/                generated HTML
```

Point `makedocs(source = STAGED_SRC, ...)` at the staging tree while retaining the existing page registry and navigation computation. Reinspect the actual target branch before producing a patch; constants and file structure may have changed.

## Build commands

Local remains the default:

```sh
julia --project=docs docs/make.jl
```

Explicit local:

```sh
DOCS_LINK_TARGET=local julia --project=docs docs/make.jl
```

Public:

```sh
DOCS_LINK_TARGET=public julia --project=docs docs/make.jl
```

A GitHub Pages job should normally build from committed `docs/src/` rather than rerunning data-dependent Literate analyses. Verify action versions from current official documentation in the deployment task; do not hard-code stale versions in this skill.
