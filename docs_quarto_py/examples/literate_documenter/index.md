---
title: "Literate and Documenter fixture"
---

This standalone Julia fixture demonstrates a Literate.jl source rendered into a Documenter.jl landing page containing HTML tables. It is kept as a nested project so it can be instantiated and built independently from the Quarto showcase.

Key files:

- [`Project.toml`](Project.toml) — the fixture's Julia environment;
- [`src/temperature_eda.jl`](src/temperature_eda.jl) — the Literate source;
- [`docs/make.jl`](docs/make.jl) — the Documenter build script; and
- [`docs/src/index.md`](docs/src/index.md) — the nested Documenter landing page.

The nested landing page remains the fixture's own documentation entry point;
this page is the Quarto-facing overview and does not replace it.
