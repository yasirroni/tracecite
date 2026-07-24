# %% [markdown]
# ---
# title: "Repository layout"
# ---

# %% [markdown]
"""
TraceCite keeps its Python and Julia implementations, tests, documentation, examples, and build tools in separate top-level areas.
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
Executable documentation examples are grouped by language under `docs/examples/`. The standalone Literate/Documenter fixture is also kept under `docs/examples/literate_documenter/`, with its own Julia project and nested Documenter site. Written guides and format references remain under `docs/guide/` and `docs/formats/`.

The project contains no `.qmd` files. Executable pages use percent-format `.py` and `.jl`; written pages use `.md`.
"""
