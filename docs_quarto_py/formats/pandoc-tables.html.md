---
title: "Pandoc Markdown tables"
---

## Native pipe table

| Rank | Station | Date | Daily maximum temperature (°C) |
|---:|---|---|---:|
| 1 | Oodnadatta Airport | 1960-01-02 | 50.7 |
| 2 | Mardie | 2022-01-13 | 50.5 |

: A captioned pipe table that is directly readable by people and Pandoc. {#tbl-pandoc-pipe}

## Grid table

+------+----------------------+-------------+
| Rank | Technology           | Cost (\$/kW) |
+======+======================+=============+
| 1    | Solar PV             | 1250        |
+------+----------------------+-------------+
| 2    | Battery BESS         | 890.5       |
+------+----------------------+-------------+

: A grid table discovered through the Pandoc AST. {#tbl-pandoc-grid}

## Multiline table

-------------------------------------------------------------
 Centered   Default           Right Left
  Header    Aligned         Aligned Aligned
----------- ------- --------------- -------------------------
   First    row                12.0 Example of a row that
                                    spans multiple lines.

  Second    row                 5.0 Here's another one. Note
                                    the blank line between
                                    rows.
-------------------------------------------------------------

: A multiline table whose headers and cells span source lines. {#tbl-pandoc-multiline}

The document extractor preserves exact source for ordinary pipe tables. For complex Pandoc tables whose source boundaries are ambiguous, it stores Pandoc's canonical table representation and emits an explicit diagnostic.
