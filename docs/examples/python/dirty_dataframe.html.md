---
title: "Dirty DataFrame edge cases — Python"
subtitle: "HTML MIME and native Pandoc tables from the same data"
---

## Purpose

This page intentionally includes Markdown-sensitive values, missing values, currency text, units, links, and literal pipes. The first display uses pandas HTML MIME output. The second uses the optional native Pandoc table helper. TraceCite normalises both through one canonical model.

::: {#dirty-dataframe-setup .cell execution_count=1}
``` {.python .cell-code}
import pandas as pd

from tracecite.tables import knowledge_table


dirty_table = pd.DataFrame(
    {
        "technology": [
            "Solar PV",
            "Battery | BESS",
            "Gas *peaker*",
            "Hydrogen <draft>",
            "Demand response",
        ],
        "capital_cost_per_kw": [1250.0, 890.5, 760.0, None, 140.0],
        "variable_cost_per_mwh": [0.0, 12.4, 185.0, 240.0, -15.0],
        "status": ["firm", "provisional", "review", "missing", "credit"],
        "notes": [
            "Currency: A$1,250/kW",
            "literal pipe: north | south",
            "emphasis must remain literal",
            "HTML-looking text must be escaped",
            "negative value is intentional",
        ],
    }
)
```
:::


## HTML MIME display

A bare DataFrame is useful for direct inspection and may appear as an HTML table in retained Markdown. The HTML adapter preserves that source and converts it to canonical Markdown for retrieval.

::: {#cell-dirty-dataframe-html-display .cell execution_count=2}
``` {.python .cell-code}
dirty_table
```

::: {#dirty-dataframe-html-display .cell-output .cell-output-display execution_count=2}
```{=html}
<div>
<style scoped>
    .dataframe tbody tr th:only-of-type {
        vertical-align: middle;
    }

    .dataframe tbody tr th {
        vertical-align: top;
    }

    .dataframe thead th {
        text-align: right;
    }
</style>
<table border="1" class="dataframe">
  <thead>
    <tr style="text-align: right;">
      <th></th>
      <th>technology</th>
      <th>capital_cost_per_kw</th>
      <th>variable_cost_per_mwh</th>
      <th>status</th>
      <th>notes</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th>0</th>
      <td>Solar PV</td>
      <td>1250.0</td>
      <td>0.0</td>
      <td>firm</td>
      <td>Currency: A$1,250/kW</td>
    </tr>
    <tr>
      <th>1</th>
      <td>Battery | BESS</td>
      <td>890.5</td>
      <td>12.4</td>
      <td>provisional</td>
      <td>literal pipe: north | south</td>
    </tr>
    <tr>
      <th>2</th>
      <td>Gas *peaker*</td>
      <td>760.0</td>
      <td>185.0</td>
      <td>review</td>
      <td>emphasis must remain literal</td>
    </tr>
    <tr>
      <th>3</th>
      <td>Hydrogen &lt;draft&gt;</td>
      <td>NaN</td>
      <td>240.0</td>
      <td>missing</td>
      <td>HTML-looking text must be escaped</td>
    </tr>
    <tr>
      <th>4</th>
      <td>Demand response</td>
      <td>140.0</td>
      <td>-15.0</td>
      <td>credit</td>
      <td>negative value is intentional</td>
    </tr>
  </tbody>
</table>
</div>
```
:::
:::


## Native Pandoc tables

`knowledge_table()` needs a stable table identifier. A caption is optional, so
the minimal form emits a bare pipe table without a numbered Quarto caption.

::: {#dirty-dataframe-pandoc-minimal .cell execution_count=3}
``` {.python .cell-code}
print(
    knowledge_table(
        dirty_table,
        table_id="dirty-dataframe-python-minimal",  # Required: stable TraceCite identity.
    )
)
```
<!-- tracecite-table: {"table_id": "dirty-dataframe-python-minimal"} -->

| technology             |   capital cost per kw |   variable cost per mwh | status      | notes                             |
|:-----------------------|----------------------:|------------------------:|:------------|:----------------------------------|
| Solar PV               |                  1250 |                       0 | firm        | Currency: A\$1,250/kW             |
| Battery \| BESS        |                 890.5 |                    12.4 | provisional | literal pipe: north \| south      |
| Gas \*peaker\*         |                   760 |                     185 | review      | emphasis must remain literal      |
| Hydrogen &lt;draft&gt; |         not available |                     240 | missing     | HTML-looking text must be escaped |
| Demand response        |                   140 |                     -15 | credit      | negative value is intentional     |

:::


Optional metadata controls presentation, retrieval context, stable row identity,
and the data-derived finding. TraceCite can also normalise tables produced by
other libraries; this helper is a convenient Pandoc Markdown output route.

::: {#dirty-dataframe-pandoc-advanced .cell execution_count=4}
``` {.python .cell-code}
print(
    knowledge_table(
        dirty_table,
        table_id="tbl-dirty-python",  # Required: stable identity and Quarto target.
        caption="Technology costs.",  # Optional: visible caption enabling Quarto references.
        labels={  # Optional: reader-facing column headings.
            "technology": "Technology",
            "capital_cost_per_kw": "Capital cost ($/kW)",
            "variable_cost_per_mwh": "Variable cost ($/MWh)",
            "status": "Status",
            "notes": "Notes",
        },
        formats={  # Optional: deterministic numeric display formats.
            "capital_cost_per_kw": ".2f",
            "variable_cost_per_mwh": ".2f",
        },
        units={  # Optional: units retained in retrieval metadata and findings.
            "capital_cost_per_kw": "$/kW",
            "variable_cost_per_mwh": "$/MWh",
        },
        row_identity=["technology"],  # Optional: logical identity for stable row IDs.
        summary=[  # Optional: first field is the subject of the generated finding.
            "technology", "capital_cost_per_kw", "status"
        ],
    )
)
```
<!-- tracecite-table: {"row_identity": ["Technology"], "units": {"Capital cost ($/kW)": "$/kW", "Variable cost ($/MWh)": "$/MWh"}} -->

| Technology             |   Capital cost (\$/kW) |   Variable cost (\$/MWh) | Status      | Notes                             |
|:-----------------------|-----------------------:|-------------------------:|:------------|:----------------------------------|
| Solar PV               |                1250.00 |                     0.00 | firm        | Currency: A\$1,250/kW             |
| Battery \| BESS        |                 890.50 |                    12.40 | provisional | literal pipe: north \| south      |
| Gas \*peaker\*         |                 760.00 |                   185.00 | review      | emphasis must remain literal      |
| Hydrogen &lt;draft&gt; |          not available |                   240.00 | missing     | HTML-looking text must be escaped |
| Demand response        |                 140.00 |                   -15.00 | credit      | negative value is intentional     |

: Technology costs. {#tbl-dirty-python}

**First-row finding.** For **Solar PV**, capital cost ($/kW) is **1250.00 \$/kW** and status is **firm**.
:::



