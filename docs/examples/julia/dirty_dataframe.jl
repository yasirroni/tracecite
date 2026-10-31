# %% [markdown]
# ---
# title: "TraceCite with Julia"
# subtitle: "The optional Julia route into TraceCite's canonical table model"
# ---

# %% [markdown]
"""
## Julia is optional

Julia is optional. TraceCite's Python normaliser and CLI do not require Julia.
Rendering this executable page requires Julia 1.10 or newer, DataFrames.jl,
Tables.jl, and Quarto's Julia engine.

This page uses the same table contract as the Python introduction: HTML MIME
and native Pandoc output are two evidence routes into TraceCite's canonical
model.
"""

# %%
#| label: dirty-dataframe-setup
#| output: false
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
## Evidence route 1: HTML MIME

A bare DataFrame is a normal Julia evidence route. Its retained HTML is
preserved, and TraceCite can convert it to canonical Markdown and retrieval
records without requiring the native helper. The same HTML adapter handles
Literate and Documenter output.
"""

# %%
#| label: dirty-dataframe-html-display
dirty_table

# %% [markdown]
"""
## Evidence route 2: Native Pandoc tables

`knowledge_table()` needs a stable table identifier. A caption is optional, so
the minimal form emits a bare pipe table without a numbered Quarto caption.
"""

# %%
#| label: dirty-dataframe-pandoc-minimal
#| output: asis

println(
    knowledge_table(
        dirty_table;
        table_id = "dirty-dataframe-julia-minimal", # Required: stable TraceCite identity.
    ),
)

# %% [markdown]
"""
The advanced call below controls presentation, retrieval context, stable row
identity, and the data-derived finding. TraceCite can also normalise tables
produced by other libraries; this helper is a convenient Pandoc Markdown output
route.
"""

# %%
#| label: dirty-dataframe-pandoc-advanced
#| output: asis

println(
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

# %% [markdown]
"""
`computed_first_row_summary()` returns the finding on its own, for prose outside
a table. With a single field, the finding states that field's value.
"""

# %%
#| label: dirty-dataframe-first-row-summary
#| output: asis

println(computed_first_row_summary(dirty_table; columns = ["status"]))

# %%
#| label: dirty-dataframe-assertions
#| include: false

using Dates

@assert computed_first_row_summary(dirty_table; columns = String[]) ==
    "**First-row finding.** No fields were selected."
@assert computed_first_row_summary(dirty_table[1:0, :]; columns = ["status"]) ==
    "**First-row finding.** The table contains no rows."
@assert endswith(
    knowledge_table(dirty_table; table_id = "tbl-no-summary-fields", summary = String[]),
    "\n**First-row finding.** No fields were selected.",
)

events = DataFrame(
    place = ["North", "North"],
    date = [Date("1960-01-02"), Date("1961-03-04")],
    temperature = [50.7, 49.1],
)
event_table = knowledge_table(
    events;
    table_id = "tbl-events",
    ordering = "temperature descending",
    row_identity = ["place", "date"],
)
@assert occursin("| 1960-01-02 |", event_table)
@assert occursin("\"ordering\":\"temperature descending\"", event_table)
@assert occursin("\"row_identity\":[\"place\",\"date\"]", event_table)

# %% [markdown]
"""
## What the canonical model provides

For either input route, TraceCite derives:

- raw source evidence;
- canonical Markdown;
- normalised retrieval text;
- table-level and row-level records; and
- diagnostics, identifiers, and source hashes.

These are retrieval representations, not embedding vectors.
"""
