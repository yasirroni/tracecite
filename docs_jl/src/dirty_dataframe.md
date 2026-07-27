```@meta
EditURL = "examples/julia/dirty_dataframe.jl"
```

# TraceCite with Julia

*The optional Julia route into TraceCite's canonical table model*

## Julia is optional

Julia is optional. TraceCite's Python normaliser and CLI do not require Julia.
Rendering this executable page requires Julia 1.10 or newer, DataFrames.jl,
and Tables.jl. The Quarto site uses Quarto's Julia engine; the standalone
Documenter site executes the same canonical source through Literate.jl.

This page uses the same table contract as the Python introduction: HTML MIME
and native Pandoc output are two evidence routes into TraceCite's canonical
model.

````@example dirty_dataframe
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
````

## Evidence route 1: HTML MIME

The native Julia engine can retain a rich HTML table representation. TraceCite handles it through the same HTML adapter used for Literate and Documenter output.

````@example dirty_dataframe
dirty_table
````

## Evidence route 2: Native Pandoc tables

`knowledge_table()` needs a stable table identifier. A caption is optional, so
the minimal form emits a bare pipe table without a numbered Quarto caption.

````@example dirty_dataframe
print(
    knowledge_table(
        dirty_table;
        table_id = "dirty-dataframe-julia-minimal", # Required: stable TraceCite identity.
    ),
)
````

The advanced call below controls presentation, retrieval context, stable row
identity, and the data-derived finding. TraceCite can also normalise tables
produced by other libraries; this helper is a convenient Pandoc Markdown output
route.

````@example dirty_dataframe
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


@assert size(dirty_table) == (5, 5) # hide
@assert "Battery | BESS" in dirty_table.technology # hide
````

---

*This page was generated using [Literate.jl](https://github.com/fredrikekre/Literate.jl).*

