---
title: "Control code visibility in Quarto"
subtitle: "Show, hide, or fold executable source without changing table output"
format:
  html:
    code-fold: false
---

## Presentation-only controls

This Python-only tutorial demonstrates Quarto presentation controls, not a new
TraceCite transformation. The page locally disables the project-wide folding
default so the first executable cell is visibly shown. Each cell still emits
ordinary TraceCite-compatible Markdown with a stable table identifier.

::: {#quarto-visibility-setup .cell execution_count=1}
``` {.python .cell-code}
import pandas as pd

from tracecite.tables import knowledge_table


example = pd.DataFrame(
    {"method": ["visible", "hidden", "folded"], "count": [1, 2, 3]}
)
```
:::


## Visible source

This cell uses the normal default presentation. Because this page sets
`format.html.code-fold: false`, its executable source is visible in the HTML.

::: {#quarto-visible-table .cell execution_count=2}
``` {.python .cell-code}
print(knowledge_table(example, table_id="quarto-visible-table"))
```
<!-- tracecite-table: {"table_id": "quarto-visible-table"} -->

| method   |   count |
|:---------|--------:|
| visible  |       1 |
| hidden   |       2 |
| folded   |       3 |

:::


## Hidden source

The next cell uses `#| echo: false` to hide its source while retaining its
executed table output. The option affects HTML presentation only.

::: {#quarto-hidden-table .cell execution_count=3}
<!-- tracecite-table: {"table_id": "quarto-hidden-table"} -->

| method   |   count |
|:---------|--------:|
| visible  |       1 |
| hidden   |       2 |
| folded   |       3 |

:::


## Folded source

The final cell opts back into folding with `#| code-fold: true` and labels the
closed control with `#| code-summary: "Show the table-generating code"`.

::: {#quarto-folded-table .cell execution_count=4}
``` {.python .cell-code code-fold="true" code-summary="Show the table-generating code"}
print(knowledge_table(example, table_id="quarto-folded-table"))
```
<!-- tracecite-table: {"table_id": "quarto-folded-table"} -->

| method   |   count |
|:---------|--------:|
| visible  |       1 |
| hidden   |       2 |
| folded   |       3 |

:::


## What remains unchanged

All three calls emit equivalent TraceCite-compatible Markdown. Code visibility
options do not change the emitted Markdown, TraceCite metadata, normalisation,
or retrieval records.


