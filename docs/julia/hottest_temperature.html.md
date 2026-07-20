---
title: "Highest-temperature EDA — Julia"
subtitle: "The DataFrames.jl counterpart to the Python page"
---

## Purpose

The page computes the same ranked event table as the Python counterpart. The observed result is generated from the source data. Quarto's native Julia engine executes the page, retains Markdown, and produces the HTML site.

::: {#2 .cell execution_count=1}
``` {.julia .cell-code}
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
```

::: {.cell-output .cell-output-display execution_count=1}
```{=html}
<div><div style = "float: left;"><span>4×4 DataFrame</span></div><div style = "clear: both;"></div></div><div class = "data-frame" style = "overflow-x: scroll;"><table class = "data-frame" style = "margin-bottom: 6px;"><thead><tr class = "columnLabelRow"><th class = "stubheadLabel" style = "font-weight: bold; text-align: right;">Row</th><th style = "text-align: left;">rank</th><th style = "text-align: left;">place</th><th style = "text-align: left;">date</th><th style = "text-align: left;">daily_maximum_temperature_c</th></tr><tr class = "columnLabelRow"><th class = "stubheadLabel" style = "font-weight: bold; text-align: right;"></th><th title = "Int64" style = "text-align: left;">Int64</th><th title = "String" style = "text-align: left;">String</th><th title = "Dates.Date" style = "text-align: left;">Date</th><th title = "Float64" style = "text-align: left;">Float64</th></tr></thead><tbody><tr class = "dataRow"><td class = "rowLabel" style = "font-weight: bold; text-align: right;">1</td><td style = "text-align: right;">1</td><td style = "text-align: left;">Oodnadatta Airport, South Australia</td><td style = "text-align: left;">1960-01-02</td><td style = "text-align: right;">50.7</td></tr><tr class = "dataRow"><td class = "rowLabel" style = "font-weight: bold; text-align: right;">2</td><td style = "text-align: right;">2</td><td style = "text-align: left;">Onslow Airport, Western Australia</td><td style = "text-align: left;">2022-01-13</td><td style = "text-align: right;">50.7</td></tr><tr class = "dataRow"><td class = "rowLabel" style = "font-weight: bold; text-align: right;">3</td><td style = "text-align: right;">3</td><td style = "text-align: left;">Mardie, Western Australia</td><td style = "text-align: left;">2022-01-13</td><td style = "text-align: right;">50.5</td></tr><tr class = "dataRow"><td class = "rowLabel" style = "font-weight: bold; text-align: right;">4</td><td style = "text-align: right;">4</td><td style = "text-align: left;">Roebourne, Western Australia</td><td style = "text-align: left;">2022-01-13</td><td style = "text-align: right;">50.5</td></tr></tbody></table></div>
```
:::
:::



## Highest observed daily maximum temperatures

The published output is an ordinary Pandoc table. The metadata describes schema semantics only; the rows are generated from the DataFrame.

<!-- tracecite-table: {"units":{"Daily maximum temperature (°C)":"°C"},"row_identity":["Place","Date"],"description":"Highest daily maximum-temperature events in the example dataset.","ordering":"Daily maximum temperature descending, then Date ascending, then Place ascending"} -->

| Rank | Place | Date | Daily maximum temperature (°C) |
| ---: | :--- | :--- | ---: |
| 1 | Oodnadatta Airport, South Australia | 1960-01-02 | 50.7 |
| 2 | Onslow Airport, Western Australia | 2022-01-13 | 50.7 |
| 3 | Mardie, Western Australia | 2022-01-13 | 50.5 |
| 4 | Roebourne, Western Australia | 2022-01-13 | 50.5 |

: Highest observed daily maximum temperatures, ordered from highest to lowest. {#tbl-highest-temperature-julia}




