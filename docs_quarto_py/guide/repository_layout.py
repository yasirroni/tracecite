# %% [markdown]
# ---
# title: "Repository layout"
# ---

# %% [markdown]
"""
TraceCite keeps implementation, tests, build tools, and published documentation separate. User-facing examples live with the documentation under `docs/examples/` rather than in a parallel top-level example tree.
"""

# %%
#| label: repository-layout-tree
#| echo: false
#| output: asis

from pathlib import Path
import sys


def repository_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "Project.toml"
        ).is_file():
            return candidate
    raise RuntimeError("Could not locate the TraceCite repository root")


ROOT = repository_root(Path.cwd().resolve())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.render_repository_tree import render_repository_tree

print("```text")
print(render_repository_tree(ROOT, max_depth=3))
print("```")

# %% [markdown]
"""
Executable tutorials are grouped by language under `docs/examples/`. Source-backed examples own their pages and source files in the same workspace: the workbook example lives under `docs/examples/workbook-vector-search/`, while the AEMO report-adoption workflow remains self-contained under `docs/examples/report-adoption/`. The standalone Literate/Documenter fixture remains under `docs/examples/literate_documenter/`. Written guides and format references remain under `docs/guide/` and `docs/formats/`.

Most executable pages use percent-format `.py` and `.jl`, while written pages use `.md`. The report-adoption example intentionally uses one authored `.qmd` file because it demonstrates how an external Quarto project produces retained Markdown for TraceCite.
"""
