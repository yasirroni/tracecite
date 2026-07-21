---
title: "Literate and Documenter HTML tables"
---

Literate.jl and Documenter.jl can preserve a table as raw HTML MIME output. The HTML adapter keeps the original markup and creates a canonical Markdown table before normalisation.

Both ordinary raw HTML and Documenter/Pandoc raw blocks are recognised:

````markdown
```@raw html
<table>...</table>
```

```{=html}
<table>...</table>
```
````

<table id="tbl-documenter-weather">
<caption>Documenter HTML MIME weather table.</caption>
<thead>
<tr><th rowspan="2">Place</th><th colspan="2">Observed event</th></tr>
<tr><th>Date</th><th>Temperature (°C)</th></tr>
</thead>
<tbody>
<tr><td>Oodnadatta Airport</td><td>1960-01-02</td><td>50.7</td></tr>
<tr><td>Mardie</td><td>2022-01-13</td><td>50.5</td></tr>
</tbody>
</table>

The row and column spans are expanded deterministically in the canonical model and recorded as `table.span-expanded` diagnostics. Nested tables are not silently flattened.

A minimal Literate/Documenter project using this route is included under `docs/examples/literate_documenter/`.

After Quarto produces retained Markdown, the public `tracecite prepare` command can create the optional inspection-site copy. `scripts/build_docs.py` coordinates that command for this repository; it does not implement HTML table normalisation. External projects can invoke `tracecite prepare` directly after their own Quarto render.
