---
title: "Dirty DataFrame edge cases — Julia"
subtitle: "HTML MIME and native Pandoc tables from the same data"
---

## Purpose

This page uses the same values and section structure as the Python counterpart. The first display uses DataFrames.jl's rich table output. The second emits native Pandoc Markdown through `TraceCite.knowledge_table`.

::: {#2 .cell execution_count=1}
``` {.julia .cell-code}
using DataFrames
using TraceCite


dirty_table = DataFrame(
    technology = [
        "Solar PV",
        "Battery | BESS",
        "Gas *peaker*",
        "Hydrogen <draft>",
        "Demand response",
    ],
    capital_cost_per_kw = Union{Missing, Float64}[1250.0, 890.5, 760.0, missing, 140.0],
    variable_cost_per_mwh = [0.0, 12.4, 185.0, 240.0, -15.0],
    status = ["firm", "provisional", "review", "missing", "credit"],
    notes = [
        "Currency: A\$1,250/kW",
        "literal pipe: north | south",
        "emphasis must remain literal",
        "HTML-looking text must be escaped",
        "negative value is intentional",
    ],
)
```

::: {.cell-output .cell-output-display execution_count=1}
```{=html}
<div><div style = "float: left;"><span>5×5 DataFrame</span></div><div style = "clear: both;"></div></div><div class = "data-frame" style = "overflow-x: scroll;"><table class = "data-frame" style = "margin-bottom: 6px;"><thead><tr class = "columnLabelRow"><th class = "stubheadLabel" style = "font-weight: bold; text-align: right;">Row</th><th style = "text-align: left;">technology</th><th style = "text-align: left;">capital_cost_per_kw</th><th style = "text-align: left;">variable_cost_per_mwh</th><th style = "text-align: left;">status</th><th style = "text-align: left;">notes</th></tr><tr class = "columnLabelRow"><th class = "stubheadLabel" style = "font-weight: bold; text-align: right;"></th><th title = "String" style = "text-align: left;">String</th><th title = "Union{Missing, Float64}" style = "text-align: left;">Float64?</th><th title = "Float64" style = "text-align: left;">Float64</th><th title = "String" style = "text-align: left;">String</th><th title = "String" style = "text-align: left;">String</th></tr></thead><tbody><tr class = "dataRow"><td class = "rowLabel" style = "font-weight: bold; text-align: right;">1</td><td style = "text-align: left;">Solar PV</td><td style = "text-align: right;">1250.0</td><td style = "text-align: right;">0.0</td><td style = "text-align: left;">firm</td><td style = "text-align: left;">Currency: A$1,250/kW</td></tr><tr class = "dataRow"><td class = "rowLabel" style = "font-weight: bold; text-align: right;">2</td><td style = "text-align: left;">Battery | BESS</td><td style = "text-align: right;">890.5</td><td style = "text-align: right;">12.4</td><td style = "text-align: left;">provisional</td><td style = "text-align: left;">literal pipe: north | south</td></tr><tr class = "dataRow"><td class = "rowLabel" style = "font-weight: bold; text-align: right;">3</td><td style = "text-align: left;">Gas *peaker*</td><td style = "text-align: right;">760.0</td><td style = "text-align: right;">185.0</td><td style = "text-align: left;">review</td><td style = "text-align: left;">emphasis must remain literal</td></tr><tr class = "dataRow"><td class = "rowLabel" style = "font-weight: bold; text-align: right;">4</td><td style = "text-align: left;">Hydrogen &lt;draft&gt;</td><td style = "font-style: italic; text-align: right;">missing</td><td style = "text-align: right;">240.0</td><td style = "text-align: left;">missing</td><td style = "text-align: left;">HTML-looking text must be escaped</td></tr><tr class = "dataRow"><td class = "rowLabel" style = "font-weight: bold; text-align: right;">5</td><td style = "text-align: left;">Demand response</td><td style = "text-align: right;">140.0</td><td style = "text-align: right;">-15.0</td><td style = "text-align: left;">credit</td><td style = "text-align: left;">negative value is intentional</td></tr></tbody></table></div>
```
:::
:::



## HTML MIME display

The native Julia engine can retain a rich HTML table representation. TraceCite handles it through the same HTML adapter used for Literate and Documenter output.

::: {#4 .cell execution_count=1}
``` {.julia .cell-code}
dirty_table
```

::: {.cell-output .cell-output-display execution_count=1}
```{=html}
<div><div style = "float: left;"><span>5×5 DataFrame</span></div><div style = "clear: both;"></div></div><div class = "data-frame" style = "overflow-x: scroll;"><table class = "data-frame" style = "margin-bottom: 6px;"><thead><tr class = "columnLabelRow"><th class = "stubheadLabel" style = "font-weight: bold; text-align: right;">Row</th><th style = "text-align: left;">technology</th><th style = "text-align: left;">capital_cost_per_kw</th><th style = "text-align: left;">variable_cost_per_mwh</th><th style = "text-align: left;">status</th><th style = "text-align: left;">notes</th></tr><tr class = "columnLabelRow"><th class = "stubheadLabel" style = "font-weight: bold; text-align: right;"></th><th title = "String" style = "text-align: left;">String</th><th title = "Union{Missing, Float64}" style = "text-align: left;">Float64?</th><th title = "Float64" style = "text-align: left;">Float64</th><th title = "String" style = "text-align: left;">String</th><th title = "String" style = "text-align: left;">String</th></tr></thead><tbody><tr class = "dataRow"><td class = "rowLabel" style = "font-weight: bold; text-align: right;">1</td><td style = "text-align: left;">Solar PV</td><td style = "text-align: right;">1250.0</td><td style = "text-align: right;">0.0</td><td style = "text-align: left;">firm</td><td style = "text-align: left;">Currency: A$1,250/kW</td></tr><tr class = "dataRow"><td class = "rowLabel" style = "font-weight: bold; text-align: right;">2</td><td style = "text-align: left;">Battery | BESS</td><td style = "text-align: right;">890.5</td><td style = "text-align: right;">12.4</td><td style = "text-align: left;">provisional</td><td style = "text-align: left;">literal pipe: north | south</td></tr><tr class = "dataRow"><td class = "rowLabel" style = "font-weight: bold; text-align: right;">3</td><td style = "text-align: left;">Gas *peaker*</td><td style = "text-align: right;">760.0</td><td style = "text-align: right;">185.0</td><td style = "text-align: left;">review</td><td style = "text-align: left;">emphasis must remain literal</td></tr><tr class = "dataRow"><td class = "rowLabel" style = "font-weight: bold; text-align: right;">4</td><td style = "text-align: left;">Hydrogen &lt;draft&gt;</td><td style = "font-style: italic; text-align: right;">missing</td><td style = "text-align: right;">240.0</td><td style = "text-align: left;">missing</td><td style = "text-align: left;">HTML-looking text must be escaped</td></tr><tr class = "dataRow"><td class = "rowLabel" style = "font-weight: bold; text-align: right;">5</td><td style = "text-align: left;">Demand response</td><td style = "text-align: right;">140.0</td><td style = "text-align: right;">-15.0</td><td style = "text-align: left;">credit</td><td style = "text-align: left;">negative value is intentional</td></tr></tbody></table></div>
```
:::
:::



## Native Pandoc tables

`knowledge_table()` needs a stable table identifier. A caption is optional, so
the minimal form emits a bare pipe table without a numbered Quarto caption.

``` {.julia .cell-code}
print(
    knowledge_table(
        dirty_table;
        table_id = "dirty-dataframe-julia-minimal", # Required: stable TraceCite identity.
    ),
)
```
<!-- tracecite-table: {"table_id":"dirty-dataframe-julia-minimal"} -->

| technology | capital cost per kw | variable cost per mwh | status | notes |
| :--- | ---: | ---: | :--- | :--- |
| Solar PV | 1250 | 0 | firm | Currency: A\$1,250/kW |
| Battery \| BESS | 890.5 | 12.4 | provisional | literal pipe: north \| south |
| Gas \*peaker\* | 760 | 185 | review | emphasis must remain literal |
| Hydrogen &lt;draft&gt; | not available | 240 | missing | HTML-looking text must be escaped |
| Demand response | 140 | -15 | credit | negative value is intentional |


Optional metadata controls presentation, retrieval context, stable row identity,
and the data-derived finding. TraceCite can also normalise tables produced by
other libraries; this helper is a convenient Pandoc Markdown output route.

``` {.julia .cell-code}
print(
    knowledge_table(
        dirty_table;
        table_id = "tbl-dirty-julia", # Required: stable identity and Quarto target.
        caption = "Technology costs.", # Optional: visible caption enabling Quarto references.
        labels = Dict( # Optional: reader-facing column headings.
            "technology" => "Technology",
            "capital_cost_per_kw" => "Capital cost (\$/kW)",
            "variable_cost_per_mwh" => "Variable cost (\$/MWh)",
            "status" => "Status",
            "notes" => "Notes",
        ),
        formats = Dict( # Optional: deterministic numeric display formats.
            "capital_cost_per_kw" => ".2f",
            "variable_cost_per_mwh" => ".2f",
        ),
        units = Dict( # Optional: units retained in retrieval metadata and findings.
            "capital_cost_per_kw" => "\$/kW",
            "variable_cost_per_mwh" => "\$/MWh",
        ),
        row_identity = ["technology"], # Optional: logical identity for stable row IDs.
        summary = [ # Optional: first field is the subject of the generated finding.
            "technology", "capital_cost_per_kw", "status"
        ],
    ),
)
```
<!-- tracecite-table: {"units":{"Variable cost ($/MWh)":"$/MWh","Capital cost ($/kW)":"$/kW"},"row_identity":["Technology"]} -->

| Technology | Capital cost (\$/kW) | Variable cost (\$/MWh) | Status | Notes |
| :--- | ---: | ---: | :--- | :--- |
| Solar PV | 1250.00 | 0.00 | firm | Currency: A\$1,250/kW |
| Battery \| BESS | 890.50 | 12.40 | provisional | literal pipe: north \| south |
| Gas \*peaker\* | 760.00 | 185.00 | review | emphasis must remain literal |
| Hydrogen &lt;draft&gt; | not available | 240.00 | missing | HTML-looking text must be escaped |
| Demand response | 140.00 | -15.00 | credit | negative value is intentional |

: Technology costs. {#tbl-dirty-julia}

**First-row finding.** For **Solar PV**, capital cost ($/kW) is **1250.00 \$/kW** and status is **firm**.




