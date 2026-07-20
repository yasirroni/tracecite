---
title: "Dirty DataFrame edge cases — Python"
subtitle: "HTML MIME and native Pandoc tables from the same data"
---

## Purpose

This page intentionally includes Markdown-sensitive values, missing values, currency text, units, links, and literal pipes. The first display uses pandas HTML MIME output. The second uses the optional native Pandoc table helper. TraceCite normalises both through one canonical model.

::: {#a55c2548 .cell execution_count=1}
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

::: {#d57a8ccc .cell execution_count=2}
``` {.python .cell-code}
dirty_table
```

::: {.cell-output .cell-output-display execution_count=2}
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


## Native Pandoc table

The same values are emitted as a safe captioned pipe table. This remains optional; TraceCite also accepts tables produced by other libraries.

<!-- tracecite-table: {"row_identity": ["Technology"], "units": {"Capital cost ($/kW)": "$/kW", "Variable cost ($/MWh)": "$/MWh"}} -->

| Technology             |   Capital cost (\$/kW) |   Variable cost (\$/MWh) | Status      | Notes                             |
|:-----------------------|-----------------------:|-------------------------:|:------------|:----------------------------------|
| Solar PV               |                1250.00 |                     0.00 | firm        | Currency: A\$1,250/kW             |
| Battery \| BESS        |                 890.50 |                    12.40 | provisional | literal pipe: north \| south      |
| Gas \*peaker\*         |                 760.00 |                   185.00 | review      | emphasis must remain literal      |
| Hydrogen &lt;draft&gt; |          not available |                   240.00 | missing     | HTML-looking text must be escaped |
| Demand response        |                 140.00 |                   -15.00 | credit      | negative value is intentional     |

: Dirty technology-cost fixture emitted as native Pandoc Markdown. {#tbl-dirty-python}

**Computed finding.** In `Dirty technology-cost fixture emitted as native Pandoc Markdown.`, the first row has Technology is **Solar PV**, Capital cost ($/kW) is **1250.00 \$/kW**, and Status is **firm**.



