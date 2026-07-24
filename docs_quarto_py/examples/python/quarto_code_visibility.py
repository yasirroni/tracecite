# %% [markdown]
# ---
# title: "Control code visibility in Quarto"
# subtitle: "Show, hide, or fold executable source without changing table output"
# format:
#   html:
#     code-fold: false
# ---

# %% [markdown]
"""
## Presentation-only controls

This Python-only tutorial demonstrates Quarto presentation controls, not a new
TraceCite transformation. The page locally disables the project-wide folding
default so the first executable cell is visibly shown. Each cell still emits
ordinary TraceCite-compatible Markdown with a stable table identifier.
"""

# %%
#| label: quarto-visibility-setup
import pandas as pd

from tracecite.tables import knowledge_table


example = pd.DataFrame(
    {"method": ["visible", "hidden", "folded"], "count": [1, 2, 3]}
)

# %% [markdown]
"""
## Visible source

This cell uses the normal default presentation. Because this page sets
`format.html.code-fold: false`, its executable source is visible in the HTML.
"""

# %%
#| label: quarto-visible-table
#| output: asis
print(knowledge_table(example, table_id="quarto-visible-table"))

# %% [markdown]
"""
## Hidden source

The next cell uses `#| echo: false` to hide its source while retaining its
executed table output. The option affects HTML presentation only.
"""

# %%
#| label: quarto-hidden-table
#| echo: false
#| output: asis
print(knowledge_table(example, table_id="quarto-hidden-table"))

# %% [markdown]
"""
## Folded source

The final cell opts back into folding with `#| code-fold: true` and labels the
closed control with `#| code-summary: "Show the table-generating code"`.
"""

# %%
#| label: quarto-folded-table
#| code-fold: true
#| code-summary: "Show the table-generating code"
#| output: asis
print(knowledge_table(example, table_id="quarto-folded-table"))

# %% [markdown]
"""
## What remains unchanged

All three calls emit equivalent TraceCite-compatible Markdown. Code visibility
options do not change the emitted Markdown, TraceCite metadata, normalisation,
or retrieval records.
"""

# %%
#| label: quarto-visibility-assertions
#| include: false
assert example.shape == (3, 2)
