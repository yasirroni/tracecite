# PDF Parsing, Assets, and Verification

## PDF extraction

`parsers/pdf.py` uses PyMuPDF. For each physical page, `page.get_text("blocks")` is filtered to text blocks and sorted into reading order by `round(y0, 1)`, then `round(x0, 1)`. Each block becomes one `ParsedChunkUnit` with the positional `logical_key` `page{NNNN}-block{NNN}`. A heading heuristic (`_looks_like_heading`: short, with no trailing sentence punctuation) sets `heading_path` for the body blocks that follow, until the next heading-like block.

A page with fewer than 20 extracted characters is treated as scanned. It goes through PyMuPDF OCR first and then the Tesseract CLI, and `pages.extraction_method` records the stage that produced the text.

The page `layout_json` stores every block's text, bbox, `heading_path`, and offsets, so a chunker- or normalisation-only change rebuilds the same units with `pdf.units_from_page_layout()` without reopening the PDF.

`chunking.group_units()` merges adjacent units on the same `physical_page` while the chunk stays under `--max-chunk-chars` (default 1200). A new `heading_path` starts a new chunk once the chunk holds body text. Consecutive headings, including short lines the parser takes for headings, therefore join the section that follows, even when its first unit alone exceeds the budget. A chunk shorter than a sixth of the budget then takes in the following sections on the same page while it stays within the budget, and reports the heading path they share. A chunk of only digits, such as a lone page number, is dropped. PDF chunks never span two pages.

## Markdown extraction

`parsers/markdown.py` parses the `#` to `######` heading hierarchy and blank-line-separated paragraphs. A paragraph longer than `DEFAULT_MAX_UNIT_CHARS = 2400` is split on whitespace, so `chunking.group_units()` never splits a unit. The `logical_key` is `<heading-path>#<heading-occurrence>:p<paragraph-index>`, with a `:sub{n}` suffix for each part of a split paragraph, so it survives line shifts elsewhere in the document. A Markdown source gets one synthetic `pages` row (`physical_page = 1`) holding the full text and a `layout_json` unit list.

## Physical-page retrieval

`tracecite page <source-path> [selector]` reads `pages.text` from SQLite. It does not rank or reopen the PDF. An omitted selector means physical page 1. A selector is a positive page, a closed range (`5-9`), an open range (`5-` or `-9`), or a comma-separated combination. Terms are expanded against the indexed pages, deduplicated, and returned in ascending order. `all` selects every indexed page and cannot be combined with another term. The whole selection is validated before anything is written to stdout, so a missing page cannot produce partial output.

Plain-text output for one page is the page text. Multiple pages are separated by physical-page delimiters. `--format json` always returns an ordered array. Each element holds the retained text, the printed label and extraction metadata, a `pdf_link`, one validated whole-page render or `null`, and validated figure crops. Each asset entry gives its database-relative identifier, validated local path, SHA-256, dimensions, labels, nearby text, and bounding box. A missing, escaped, or hash-mismatched asset fails before any JSON is printed.

`tracecite extract-pages <source-path> [selector] --output-dir <dir>` uses the same selector grammar and page-1 default. It verifies and opens the indexed PDF, writes only the selected pages, and writes a provenance manifest. The output directory must already exist, be a real directory, and be outside the source root. A source-hash mismatch, a PDF and index page-count mismatch, overlap, symlinks, or existing outputs are rejected. The PDF and manifest are staged together and rolled back together if promotion fails. The output belongs to the caller and is disposable.

## Quotation verification

`tracecite verify quote <source-path> <physical-page> <quote>` checks, in order:

1. an exact substring match against `pages.text`;
2. a normalised match that collapses all whitespace, straightens curly single and double quotes, and folds case, against the page text normalised the same way;
3. otherwise `not-found`.

A changed word never matches. An empty quotation is `structural-error`. A page outside the indexed pages is `page-not-indexed`, and an unindexed source is `source-not-indexed`; both exit with status `2`. Only `exact` and `normalised` exit with status `0`. The check ignores chunk boundaries, so a quotation can span two chunks.

## Report verification

`tracecite verify report <report.md> --root <dir> --database <db>` reads Markdown reference definitions whose destinations hold a local path plus `#page=<PAGE>`, and inline citations (`[text][<label>]`). Labels are opaque. For every citation in the body it checks that a matching definition exists, that the definition's path resolves (relative to the report's directory) to an indexed source, and that the cited page is indexed.

A blockquote line (`> "..."`) is checked only when its prose paragraph resolves to exactly one citation label. An ambiguous, missing, or empty quote association is a structural error. Each quote result gives the bound `citation_key` and resolved `source_path`, or `null` when no unique binding exists. Report verification never writes to the report.

With `--source-links docs/source-links.toml`, report verification also confirms that every cited source path has exactly one schema-v3 registry entry keyed by `local_path`. It never edits the registry or the report. `routing-documentation-source-links` owns the registry schema: a `[[source]]` array of tables with `name`, `local_path`, `public_url`, and an optional opaque `metadata` table.

## Assets

Unless sync runs with `--no-assets`, for every PDF page that is parsed, `sync._persist_assets()` writes one whole-page PNG (`pdf.render_page()`, through `page.get_pixmap()`) to `imgs/generations/<generation>/<source_pk>/page-{NNNN}.png`. It also writes one crop per embedded raster image on the page (`pdf.render_figure_crops()`, through `page.get_images()`, `extract_image()`, and `get_image_rects()`) to `imgs/generations/<generation>/<source_pk>/page-{NNN}-image-{NN}.png`. A new source renders into a staging directory in the same generation, which is renamed to the assigned `source_pk` before the asset rows are inserted. The `assets` table records each render and crop with its SHA-256, dimensions, and, for crops, bounding box.

Only embedded raster images are cropped. A figure drawn only with vector graphics has no crop; use the whole-page render.

Assets live under `imgs/` next to the database, not inside SQLite. Database rows and `doctor` validate asset paths and hashes by internal key, not by public source identity. Page JSON and PDF search results only resolve existing asset rows. Retrieval never regenerates a render or crop and never treats an unchecked database path as a filesystem path.
