---
title: "Repository layout"
---

TraceCite keeps its Python and Julia implementations, tests, documentation, examples, and build tools in separate top-level areas.

::: {#repository-layout-tree .cell execution_count=1}
```text
.
├── docs/
│   ├── examples/
│   │   ├── julia/
│   │   ├── literate_documenter/
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
│   ├── _quarto-julia.yml
│   ├── _quarto-python.yml
│   ├── _quarto.yml
│   ├── bootstrap.toml
│   ├── index.html.md
│   └── index.md
├── docs_jl/
│   ├── src/
│   │   ├── examples/
│   │   ├── formats/
│   │   ├── guide/
│   │   ├── dirty_dataframe.md
│   │   └── index.md
│   ├── make.jl
│   └── Project.toml
├── docs_quarto_jl/
│   ├── examples/
│   │   ├── julia/
│   │   ├── literate_documenter/
│   │   └── python/
│   ├── formats/
│   │   ├── diagnostics.md
│   │   ├── html-documenter.md
│   │   └── pandoc-tables.md
│   ├── guide/
│   │   ├── api.md
│   │   ├── architecture.md
│   │   ├── embedding-site.md
│   │   ├── repository_layout.html.md
│   │   └── searchable-evidence.md
│   ├── _quarto.yml
│   └── index.md
├── docs_quarto_py/
│   ├── examples/
│   │   ├── julia/
│   │   ├── literate_documenter/
│   │   └── python/
│   ├── formats/
│   │   ├── diagnostics.md
│   │   ├── html-documenter.md
│   │   └── pandoc-tables.md
│   ├── guide/
│   │   ├── api.md
│   │   ├── architecture.md
│   │   ├── embedding-site.md
│   │   ├── repository_layout.py
│   │   └── searchable-evidence.md
│   ├── _quarto.yml
│   └── index.md
├── examples/
│   └── report-adoption/
│       └── aemo-isp-comparison/
├── fixtures/
│   └── sample-report.md
├── scripts/
│   ├── bootstrap_docs.py
│   ├── compact_database.py
│   ├── diagnose_database.py
│   └── render_repository_tree.py
├── src/
│   ├── tracecite/
│   │   ├── docs/
│   │   ├── evidence/
│   │   ├── tables/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   └── cli.py
│   └── TraceCite.jl
├── test/
│   └── runtests.jl
├── tests/
│   ├── docs/
│   │   ├── __init__.py
│   │   ├── test_config.py
│   │   ├── test_contract.py
│   │   ├── test_docs_cli.py
│   │   ├── test_modes.py
│   │   ├── test_report_adoption.py
│   │   ├── test_stage.py
│   │   └── test_vectorize.py
│   ├── evidence/
│   │   ├── conftest.py
│   │   ├── measure_help.py
│   │   ├── test_asset_generations.py
│   │   ├── test_cli.py
│   │   ├── test_config.py
│   │   ├── test_database_maintenance.py
│   │   ├── test_help.py
│   │   ├── test_installation.py
│   │   ├── test_manifest.py
│   │   ├── test_parsers.py
│   │   ├── test_paths.py
│   │   ├── test_profile_cli.py
│   │   ├── test_schema_v3_contract.py
│   │   ├── test_search.py
│   │   ├── test_sync.py
│   │   ├── test_vector_backend.py
│   │   └── test_verify.py
│   ├── fixtures/
│   │   ├── docs-vector/
│   │   └── publish-only/
│   ├── test_bootstrap_docs.py
│   ├── test_build_docs.py
│   ├── test_docs.py
│   ├── test_evidence_imports.py
│   ├── test_repository_tree.py
│   ├── test_tables.py
│   └── test_version.py
├── LICENSE
├── Project.toml
├── pyproject.toml
├── README.md
└── uv.lock
```
:::


Executable documentation examples are grouped by language under `docs/examples/`. The standalone Literate/Documenter fixture is also kept under `docs/examples/literate_documenter/`, with its own Julia project and nested Documenter site. Written guides and format references remain under `docs/guide/` and `docs/formats/`.

The project contains no `.qmd` files. Executable pages use percent-format `.py` and `.jl`; written pages use `.md`.

