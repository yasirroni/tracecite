---
title: "Repository layout"
---

TraceCite keeps its Python and Julia implementations, tests, documentation, examples, and build tools in separate top-level areas.

```text
.
├── docs/
│   ├── examples/
│   │   ├── julia/
│   │   └── python/
│   ├── formats/
│   │   ├── diagnostics.html.md
│   │   ├── diagnostics.md
│   │   ├── html-documenter.html.md
│   │   ├── html-documenter.md
│   │   ├── pandoc-tables.html.md
│   │   └── pandoc-tables.md
│   ├── guide/
│   │   ├── api.html.md
│   │   ├── api.md
│   │   ├── architecture.html.md
│   │   ├── architecture.md
│   │   ├── embedding-site.html.md
│   │   ├── embedding-site.md
│   │   ├── repository_layout.html.md
│   │   ├── repository_layout.py
│   │   ├── searchable-evidence.html.md
│   │   └── searchable-evidence.md
│   ├── .gitignore
│   ├── _quarto-julia.yml
│   ├── _quarto-python.yml
│   ├── _quarto.yml
│   ├── index.html.md
│   └── index.md
├── examples/
│   └── literate_documenter/
│       ├── docs/
│       ├── src/
│       └── Project.toml
├── scripts/
│   ├── build_docs.py
│   └── render_repository_tree.py
├── src/
│   ├── tracecite/
│   │   ├── tables/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   └── cli.py
│   └── TraceCite.jl
├── test/
│   └── runtests.jl
├── tests/
│   ├── test_build_docs.py
│   ├── test_repository_tree.py
│   └── test_tables.py
├── .gitignore
├── LICENSE
├── Project.toml
├── pyproject.toml
├── README.md
└── uv.lock
```


Executable documentation examples are grouped by language under `docs/examples/`. Written guides and format references remain under `docs/guide/` and `docs/formats/`.

The project contains no `.qmd` files. Executable pages use percent-format `.py` and `.jl`; written pages use `.md`.

