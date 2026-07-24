# %% [markdown]
# ---
# title: "What TraceCite does"
# subtitle: "Preserved evidence and derived retrieval text from Python tables"
# ---

# %% [markdown]
"""
## Purpose

TraceCite accepts table evidence from ordinary Python displays and from its
native Pandoc helper. Both routes preserve the raw source while deriving one
canonical Markdown table, normalised retrieval text, row records, diagnostics,
and stable identifiers for retrieval.
"""

# %%
#| label: dirty-dataframe-setup
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
## Evidence route 1: HTML MIME

A bare DataFrame is a normal Python evidence route. Its retained HTML is
preserved, and TraceCite can convert it to canonical Markdown and retrieval
records without requiring the native helper.
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

print(
    knowledge_table(
        dirty_table,
        table_id="dirty-dataframe-python-minimal",  # Required: stable TraceCite identity.
    )
)

# %% [markdown]
"""
The minimal call above and advanced call below show the optional caption,
metadata, stable row identity, and data-derived finding. TraceCite can also normalise
tables produced by other libraries; this helper is a convenient Pandoc output
route.
"""

# %%
#| label: dirty-dataframe-pandoc-advanced
#| output: asis

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

# %%
#| label: dirty-dataframe-assertions
#| include: false

assert dirty_table.shape == (5, 5)
assert "Battery | BESS" in dirty_table["technology"].tolist()

# %% [markdown]
"""
## What the canonical model provides

For either input route, TraceCite derives:

- raw source evidence;
- canonical Markdown;
- normalised retrieval text;
- table-level and row-level records; and
- diagnostics, identifiers, and source hashes.

These are retrieval representations, not embedding vectors. The public API and
CLI inspection workflow is demonstrated in the ranked-results tutorial.
"""
