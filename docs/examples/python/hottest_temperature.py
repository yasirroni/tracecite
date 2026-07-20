# %% [markdown]
# ---
# title: "Highest-temperature EDA — Python"
# subtitle: "An executed result that can answer a later question without reloading raw data"
# ---

# %% [markdown]
"""
## Purpose

The page computes a ranked event table from the source data. When the input changes and the page is rerun, Quarto regenerates the retained Markdown and HTML. TraceCite can then retrieve the new first row directly.
"""

# %%
#| label: hottest-temperature-setup
import pandas as pd

from tracecite.tables import knowledge_table


weather_events = pd.DataFrame(
    {
        "place": [
            "Mardie, Western Australia",
            "Oodnadatta Airport, South Australia",
            "Onslow Airport, Western Australia",
            "Roebourne, Western Australia",
        ],
        "date": pd.to_datetime(
            ["2022-01-13", "1960-01-02", "2022-01-13", "2022-01-13"]
        ),
        "daily_maximum_temperature_c": [50.5, 50.7, 50.7, 50.5],
    }
)

highest_temperature = (
    weather_events.sort_values(
        ["daily_maximum_temperature_c", "date", "place"],
        ascending=[False, True, True],
        kind="stable",
    )
    .head(4)
    .reset_index(drop=True)
)
highest_temperature.insert(0, "rank", range(1, len(highest_temperature) + 1))

# %% [markdown]
"""
## Highest observed daily maximum temperatures

The published output is an ordinary Pandoc table. The optional metadata describes schema semantics only; the rows are generated from the DataFrame.
"""

# %%
#| label: hottest-temperature-pandoc-table
#| echo: false
#| output: asis

print(
    knowledge_table(
        highest_temperature,
        caption="Highest observed daily maximum temperatures, ordered from highest to lowest.",
        table_id="tbl-highest-temperature-python",
        labels={
            "rank": "Rank",
            "place": "Place",
            "date": "Date",
            "daily_maximum_temperature_c": "Daily maximum temperature (°C)",
        },
        formats={
            "date": lambda value: value.strftime("%Y-%m-%d"),
            "daily_maximum_temperature_c": ".1f",
        },
        units={"daily_maximum_temperature_c": "°C"},
        ordering=(
            "Daily maximum temperature descending, then Date ascending, "
            "then Place ascending"
        ),
        row_identity=["place", "date"],
        description="Highest daily maximum-temperature events in the example dataset.",
        summary=False,
    )
)

# %%
#| label: hottest-temperature-assertions
#| include: false

assert highest_temperature.iloc[0]["daily_maximum_temperature_c"] == 50.7
assert highest_temperature.iloc[0]["place"] == "Oodnadatta Airport, South Australia"
