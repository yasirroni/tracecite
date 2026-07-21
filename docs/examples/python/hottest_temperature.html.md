---
title: "Normalise and inspect ranked results"
subtitle: "Separate pandas ranking from TraceCite retrieval preparation"
---

## Responsibility boundary

Pandas sorts and ranks these weather rows. TraceCite does not rank data: it
records the declared ordering, validates relevant structure, and derives
canonical and normalised retrieval representations.

::: {#hottest-temperature-setup .cell execution_count=1}
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


## 1. Emit the ranked table

The ranking is complete before TraceCite receives the DataFrame. The helper
records the ordering and row identity as metadata but does not reorder rows.

::: {#hottest-temperature-pandoc-table .cell execution_count=2}
``` {.python .cell-code}
ranked_markdown = knowledge_table(
    highest_temperature,
    caption="Highest observed daily maximum temperatures.",
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
print(ranked_markdown)
```
<!-- tracecite-table: {"description": "Highest daily maximum-temperature events in the example dataset.", "ordering": "Daily maximum temperature descending, then Date ascending, then Place ascending", "row_identity": ["Place", "Date"], "units": {"Daily maximum temperature (°C)": "°C"}} -->

|   Rank | Place                               | Date       |   Daily maximum temperature (°C) |
|-------:|:------------------------------------|:-----------|---------------------------------:|
|      1 | Oodnadatta Airport, South Australia | 1960-01-02 |                             50.7 |
|      2 | Onslow Airport, Western Australia   | 2022-01-13 |                             50.7 |
|      3 | Mardie, Western Australia           | 2022-01-13 |                             50.5 |
|      4 | Roebourne, Western Australia        | 2022-01-13 |                             50.5 |

: Highest observed daily maximum temperatures. {#tbl-highest-temperature-python}
:::


## 2. Normalise and inspect through the public API

The debug renderer shows raw Markdown, canonical Markdown, normalised retrieval
text, and row records together. This inspection representation is the exact
text prepared for retrieval or a future embedding pipeline; it is not an
embedding vector, and TraceCite does not currently generate or display vectors.

::: {#hottest-temperature-debug-inspection .cell execution_count=3}
``` {.python .cell-code}
from tracecite.tables import TableContext, normalise_pandoc_table, render_debug_markdown


normalised = normalise_pandoc_table(
    ranked_markdown,
    context=TableContext(
        document_path="docs/build/examples/python/hottest_temperature.html.md",
        section_path=("Normalise and inspect ranked results",),
        source_code_path="docs/examples/python/hottest_temperature.py",
    ),
)
# Remove Markdown hard-break markers so retained source remains whitespace-clean.
print(render_debug_markdown(normalised).replace("  \n", "\n"))
```
# TraceCite table-normalisation inspection

Source document: `docs/build/examples/python/hottest_temperature.html.md`
Table identifier: `tbl-highest-temperature-python`

## Raw source

```markdown
<!-- tracecite-table: {"description": "Highest daily maximum-temperature events in the example dataset.", "ordering": "Daily maximum temperature descending, then Date ascending, then Place ascending", "row_identity": ["Place", "Date"], "units": {"Daily maximum temperature (°C)": "°C"}} -->

|   Rank | Place                               | Date       |   Daily maximum temperature (°C) |
|-------:|:------------------------------------|:-----------|---------------------------------:|
|      1 | Oodnadatta Airport, South Australia | 1960-01-02 |                             50.7 |
|      2 | Onslow Airport, Western Australia   | 2022-01-13 |                             50.7 |
|      3 | Mardie, Western Australia           | 2022-01-13 |                             50.5 |
|      4 | Roebourne, Western Australia        | 2022-01-13 |                             50.5 |

: Highest observed daily maximum temperatures. {#tbl-highest-temperature-python}
```

## Canonical Markdown

```markdown
| Rank | Place | Date | Daily maximum temperature (°C) |
| ---: | :--- | :--- | ---: |
| 1 | Oodnadatta Airport, South Australia | 1960-01-02 | 50.7 |
| 2 | Onslow Airport, Western Australia | 2022-01-13 | 50.7 |
| 3 | Mardie, Western Australia | 2022-01-13 | 50.5 |
| 4 | Roebourne, Western Australia | 2022-01-13 | 50.5 |

: Highest observed daily maximum temperatures. {#tbl-highest-temperature-python}
```

## Normalised retrieval text

```text
Table: Highest observed daily maximum temperatures.
Table identifier: tbl-highest-temperature-python
Source document: docs/build/examples/python/hottest_temperature.html.md
Executable source: docs/examples/python/hottest_temperature.py
Section: Normalise and inspect ranked results
Description: Highest daily maximum-temperature events in the example dataset.
Ordering: Daily maximum temperature descending, then Date ascending, then Place ascending
Row identity columns: Place; Date
Columns: Rank; Place; Date; Daily maximum temperature (°C)

Rank 1. Place: Oodnadatta Airport, South Australia; Date: 1960-01-02; Daily maximum temperature (°C): 50.7.

Rank 2. Place: Onslow Airport, Western Australia; Date: 2022-01-13; Daily maximum temperature (°C): 50.7.

Rank 3. Place: Mardie, Western Australia; Date: 2022-01-13; Daily maximum temperature (°C): 50.5.

Rank 4. Place: Roebourne, Western Australia; Date: 2022-01-13; Daily maximum temperature (°C): 50.5.
```

## Row records

### Row 1

Record ID: `tbl-highest-temperature-python:row-f69c2d542ee7696e`

Table: Highest observed daily maximum temperatures. Table identifier: tbl-highest-temperature-python. Source document: docs/build/examples/python/hottest_temperature.html.md. Executable source: docs/examples/python/hottest_temperature.py. Section: Normalise and inspect ranked results. Description: Highest daily maximum-temperature events in the example dataset. Ordering: Daily maximum temperature descending, then Date ascending, then Place ascending. Row identity columns: Place; Date. Columns: Rank; Place; Date; Daily maximum temperature (°C). Rank 1. Place: Oodnadatta Airport, South Australia; Date: 1960-01-02; Daily maximum temperature (°C): 50.7.

### Row 2

Record ID: `tbl-highest-temperature-python:row-03e95d6b90f0b42e`

Table: Highest observed daily maximum temperatures. Table identifier: tbl-highest-temperature-python. Source document: docs/build/examples/python/hottest_temperature.html.md. Executable source: docs/examples/python/hottest_temperature.py. Section: Normalise and inspect ranked results. Description: Highest daily maximum-temperature events in the example dataset. Ordering: Daily maximum temperature descending, then Date ascending, then Place ascending. Row identity columns: Place; Date. Columns: Rank; Place; Date; Daily maximum temperature (°C). Rank 2. Place: Onslow Airport, Western Australia; Date: 2022-01-13; Daily maximum temperature (°C): 50.7.

### Row 3

Record ID: `tbl-highest-temperature-python:row-99c23ed09ef524ef`

Table: Highest observed daily maximum temperatures. Table identifier: tbl-highest-temperature-python. Source document: docs/build/examples/python/hottest_temperature.html.md. Executable source: docs/examples/python/hottest_temperature.py. Section: Normalise and inspect ranked results. Description: Highest daily maximum-temperature events in the example dataset. Ordering: Daily maximum temperature descending, then Date ascending, then Place ascending. Row identity columns: Place; Date. Columns: Rank; Place; Date; Daily maximum temperature (°C). Rank 3. Place: Mardie, Western Australia; Date: 2022-01-13; Daily maximum temperature (°C): 50.5.

### Row 4

Record ID: `tbl-highest-temperature-python:row-750a0524cb07d01d`

Table: Highest observed daily maximum temperatures. Table identifier: tbl-highest-temperature-python. Source document: docs/build/examples/python/hottest_temperature.html.md. Executable source: docs/examples/python/hottest_temperature.py. Section: Normalise and inspect ranked results. Description: Highest daily maximum-temperature events in the example dataset. Ordering: Daily maximum temperature descending, then Date ascending, then Place ascending. Row identity columns: Place; Date. Columns: Rank; Place; Date; Daily maximum temperature (°C). Rank 4. Place: Roebourne, Western Australia; Date: 2022-01-13; Daily maximum temperature (°C): 50.5.

:::


## 3. Map the API to the public CLI

The equivalent public commands use the product terms `debug-markdown`,
`embedding-markdown`, and the `embedding inspection site`:

```sh
tracecite table normalise table.md --to debug-markdown
tracecite document normalise report.md --to embedding-markdown
tracecite prepare docs/build \
  --keep-embedding-markdown .tracecite/embedding-site \
  --render-embedding-site
```

These commands produce retrieval text and inspection pages, not vectors.


