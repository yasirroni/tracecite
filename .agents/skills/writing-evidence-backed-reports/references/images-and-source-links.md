# Images and Source Links

## Authority

Images under `imgs/` are generated derivatives. The original PDF page remains authoritative.

Use an image only after checking:

- its source path and physical page;
- that it represents the intended figure or table;
- that no crop removed labels, legends, footnotes, or context needed for interpretation;
- that the report text does not overstate what the visual establishes.

## Clickable image pattern

Use an ordinary opaque Markdown label that points to the authoritative source page:

```markdown
[![Generation outlook from the 2026 ISP](../../../imgs/generations/<generation-uuid-hex>/<source-pk>/page-014-image-00.png)][figure-source]

*Figure: generation outlook. Source: [AEMO, 2026 ISP, physical PDF page 14][figure-source].*

[figure-source]: ../../../sources/aemo/2026-integrated-system-plan-isp.pdf#page=14
```

In the image path, replace `<generation-uuid-hex>` with the actual TraceCite generation UUID-hex directory and `<source-pk>` with the internal numeric source primary key recorded for that source. The page component is three digits (`page-014`) and embedded image crops use a zero-based image index (`image-00`). Do not copy the placeholder path literally. The verifier follows the reference definition destination, not the label text; do not require labels to encode pages, figures, or tables.

## Vector-composited figures

The current indexer reliably creates whole-page renders and crops embedded raster images. A diagram composed from PDF vector primitives may not have a dedicated crop. Use the reviewed whole-page render or create a faithful crop through an explicit later workflow; do not claim that every figure was automatically extracted.

## Publication

Maintained Markdown keeps local image and PDF paths. The documentation-routing workflow may replace only the PDF reference destination with the official public URL. It must not upload private source PDFs or silently redirect generated images to unrelated remote assets.
