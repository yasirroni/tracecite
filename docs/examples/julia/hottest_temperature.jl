# %% [markdown]
# ---
# title: "Highest-temperature EDA — Julia"
# subtitle: "The DataFrames.jl counterpart to the Python page"
# ---

# %% [markdown]
"""
## Purpose

The page computes the same ranked event table as the Python counterpart. The observed result is generated from the source data. Quarto's native Julia engine executes the page, retains Markdown, and produces the HTML site.
"""

# %%
using Dates
using DataFrames
using TraceCite

weather_events = DataFrame(
    place = [
        "Mardie, Western Australia",
        "Oodnadatta Airport, South Australia",
        "Onslow Airport, Western Australia",
        "Roebourne, Western Australia",
    ],
    date = Date.(["2022-01-13", "1960-01-02", "2022-01-13", "2022-01-13"]),
    daily_maximum_temperature_c = [50.5, 50.7, 50.7, 50.5],
)

highest_temperature = sort(
    weather_events,
    [
        order(:daily_maximum_temperature_c, rev = true),
        order(:date),
        order(:place),
    ],
)[1:4, :]
insertcols!(highest_temperature, 1, :rank => 1:nrow(highest_temperature))

# %% [markdown]
"""
## Highest observed daily maximum temperatures

The published output is an ordinary Pandoc table. The metadata describes schema semantics only; the rows are generated from the DataFrame.
"""

# %%
#| echo: false
#| output: asis

print(
    knowledge_table(
        highest_temperature;
        caption = "Highest observed daily maximum temperatures, ordered from highest to lowest.",
        table_id = "tbl-highest-temperature-julia",
        labels = Dict(
            "rank" => "Rank",
            "place" => "Place",
            "date" => "Date",
            "daily_maximum_temperature_c" => "Daily maximum temperature (°C)",
        ),
        formats = Dict(
            "date" => value -> Dates.format(value, dateformat"yyyy-mm-dd"),
            "daily_maximum_temperature_c" => ".1f",
        ),
        units = Dict("daily_maximum_temperature_c" => "°C"),
        ordering = "Daily maximum temperature descending, then Date ascending, then Place ascending",
        row_identity = ["place", "date"],
        description = "Highest daily maximum-temperature events in the example dataset.",
        summary = false,
    ),
)

# %%
#| include: false

@assert highest_temperature[1, :daily_maximum_temperature_c] == 50.7
@assert highest_temperature[1, :place] == "Oodnadatta Airport, South Australia"
