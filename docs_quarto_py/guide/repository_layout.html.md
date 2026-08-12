---
title: "Repository layout"
---

TraceCite keeps implementation, tests, build tools, and published documentation separate. User-facing examples live with the documentation under `docs/examples/` rather than in a parallel top-level example tree.

::: {#repository-layout-tree .cell execution_count=1}
```text
.
├── docs/
│   ├── examples/
│   │   ├── julia/
│   │   ├── literate_documenter/
│   │   ├── python/
│   │   ├── report-adoption/
│   │   └── workbook-vector-search/
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
│   │   ├── python/
│   │   ├── report-adoption/
│   │   └── workbook-vector-search/
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
│   │   ├── searchable-evidence.html.md
│   │   └── searchable-evidence.md
│   ├── _quarto.yml
│   ├── index.html.md
│   └── index.md
├── docs_quarto_py/
│   ├── build/
│   │   ├── examples/
│   │   ├── site_libs/
│   │   └── search.json
│   ├── examples/
│   │   ├── julia/
│   │   ├── literate_documenter/
│   │   ├── python/
│   │   ├── report-adoption/
│   │   └── workbook-vector-search/
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
│   ├── site_libs/
│   │   ├── bootstrap/
│   │   ├── clipboard/
│   │   ├── quarto-html/
│   │   ├── quarto-nav/
│   │   └── quarto-search/
│   ├── _quarto.yml
│   ├── index.html.md
│   └── index.md
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
│   │   ├── test_extract_pages.py
│   │   ├── test_help.py
│   │   ├── test_installation.py
│   │   ├── test_manifest.py
│   │   ├── test_page_cli.py
│   │   ├── test_page_json.py
│   │   ├── test_page_selection.py
│   │   ├── test_page_selection_surfaces.py
│   │   ├── test_parsers.py
│   │   ├── test_paths.py
│   │   ├── test_profile_cli.py
│   │   ├── test_schema_v3_contract.py
│   │   ├── test_search.py
│   │   ├── test_search_assets.py
│   │   ├── test_source_links.py
│   │   ├── test_sync.py
│   │   ├── test_vector_backend.py
│   │   ├── test_verify.py
│   │   └── test_workbook.py
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


Executable tutorials are grouped by language under `docs/examples/`. Source-backed examples own their pages and source files in the same workspace: the workbook example lives under `docs/examples/workbook-vector-search/`, while the AEMO report-adoption workflow remains self-contained under `docs/examples/report-adoption/`. The standalone Literate/Documenter fixture remains under `docs/examples/literate_documenter/`. Written guides and format references remain under `docs/guide/` and `docs/formats/`.

Most executable pages use percent-format `.py` and `.jl`, while written pages use `.md`. The report-adoption example intentionally uses one authored `.qmd` file because it demonstrates how an external Quarto project produces retained Markdown for TraceCite.

