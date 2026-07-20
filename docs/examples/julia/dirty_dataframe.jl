# %% [markdown]
# ---
# title: "Dirty DataFrame edge cases — Julia"
# subtitle: "HTML MIME and native Pandoc tables from the same data"
# ---

# %% [markdown]
"""
## Purpose

This page uses the same values and section structure as the Python counterpart. The first display uses DataFrames.jl's rich table output. The second emits native Pandoc Markdown through `TraceCite.knowledge_table`.
"""

# %%
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

# %% [markdown]
"""
## HTML MIME display

The native Julia engine can retain a rich HTML table representation. TraceCite handles it through the same HTML adapter used for Literate and Documenter output.
"""

# %%
dirty_table

# %% [markdown]
"""
## Native Pandoc table

The same values are emitted as a safe captioned pipe table.
"""

# %%
#| echo: false
#| output: asis

print(
    knowledge_table(
        dirty_table;
        caption = "Dirty technology-cost fixture emitted as native Pandoc Markdown.",
        table_id = "tbl-dirty-julia",
        labels = Dict(
            "technology" => "Technology",
            "capital_cost_per_kw" => "Capital cost (\$/kW)",
            "variable_cost_per_mwh" => "Variable cost (\$/MWh)",
            "status" => "Status",
            "notes" => "Notes",
        ),
        formats = Dict(
            "capital_cost_per_kw" => ".2f",
            "variable_cost_per_mwh" => ".2f",
        ),
        units = Dict(
            "capital_cost_per_kw" => "\$/kW",
            "variable_cost_per_mwh" => "\$/MWh",
        ),
        row_identity = ["technology"],
        summary = ["technology", "capital_cost_per_kw", "status"],
    ),
)

# %%
#| include: false

@assert size(dirty_table) == (5, 5)
@assert "Battery | BESS" in dirty_table.technology
