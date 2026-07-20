---
title: "Highest-temperature EDA — Python"
subtitle: "An executed result that can answer a later question without reloading raw data"
---

## Purpose

The page computes a ranked event table from the source data. When the input changes and the page is rerun, Quarto regenerates the retained Markdown and HTML. TraceCite can then retrieve the new first row directly.

::: {#e6ae1c8e .cell execution_count=1}
``` {.python .cell-code}
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
```
:::


## Highest observed daily maximum temperatures

The published output is an ordinary Pandoc table. The optional metadata describes schema semantics only; the rows are generated from the DataFrame.

<!-- tracecite-table: {"description": "Highest daily maximum-temperature events in the example dataset.", "ordering": "Daily maximum temperature descending, then Date ascending, then Place ascending", "row_identity": ["Place", "Date"], "units": {"Daily maximum temperature (°C)": "°C"}} -->

|   Rank | Place                               | Date       |   Daily maximum temperature (°C) |
|-------:|:------------------------------------|:-----------|---------------------------------:|
|      1 | Oodnadatta Airport, South Australia | 1960-01-02 |                             50.7 |
|      2 | Onslow Airport, Western Australia   | 2022-01-13 |                             50.7 |
|      3 | Mardie, Western Australia           | 2022-01-13 |                             50.5 |
|      4 | Roebourne, Western Australia        | 2022-01-13 |                             50.5 |

: Highest observed daily maximum temperatures, ordered from highest to lowest. {#tbl-highest-temperature-python}



