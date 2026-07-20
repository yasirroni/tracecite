# %% [markdown]
# ---
# title: "Dirty DataFrame edge cases — Python"
# subtitle: "HTML MIME and native Pandoc tables from the same data"
# ---

# %% [markdown]
"""
## Purpose

This page intentionally includes Markdown-sensitive values, missing values, currency text, units, links, and literal pipes. The first display uses pandas HTML MIME output. The second uses the optional native Pandoc table helper. TraceCite normalises both through one canonical model.
"""

# %%
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

# %% [markdown]
"""
## HTML MIME display

A bare DataFrame is useful for direct inspection and may appear as an HTML table in retained Markdown. The HTML adapter preserves that source and converts it to canonical Markdown for retrieval.
"""

# %%
dirty_table

# %% [markdown]
"""
## Native Pandoc table

The same values are emitted as a safe captioned pipe table. This remains optional; TraceCite also accepts tables produced by other libraries.
"""

# %%
#| echo: false
#| output: asis

print(
    knowledge_table(
        dirty_table,
        caption="Dirty technology-cost fixture emitted as native Pandoc Markdown.",
        table_id="tbl-dirty-python",
        labels={
            "technology": "Technology",
            "capital_cost_per_kw": "Capital cost ($/kW)",
            "variable_cost_per_mwh": "Variable cost ($/MWh)",
            "status": "Status",
            "notes": "Notes",
        },
        formats={
            "capital_cost_per_kw": ".2f",
            "variable_cost_per_mwh": ".2f",
        },
        units={
            "capital_cost_per_kw": "$/kW",
            "variable_cost_per_mwh": "$/MWh",
        },
        row_identity=["technology"],
        summary=["technology", "capital_cost_per_kw", "status"],
    )
)

# %%
#| include: false

assert dirty_table.shape == (5, 5)
assert "Battery | BESS" in dirty_table["technology"].tolist()
