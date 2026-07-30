# PDF Parsing, Assets, and Verification

## PDF extraction

`parsers/pdf.py` uses PyMuPDF (`fitz`) exclusively, behind the `Parser` protocol in
`parsers/base.py`. Per physical page: `page.get_text("blocks")` is filtered to text blocks and
sorted into reading order (`round(y0, 1)`, then `round(x0, 1)`); each block becomes one
`ParsedChunkUnit` with a positional `logical_key` (`page{NNNN}-block{NNN}`), plus a lightweight
heading heuristic (`_looks_like_heading`: short, no trailing sentence punctuation) that seeds
`heading_path` for subsequent body blocks until the next heading-like block. The retained page
`layout_json` stores every block's text/bbox/heading_path/offsets, so a later chunker- or
normalisation-only change reconstructs the same units via `pdf.units_from_page_layout()` without
reopening the PDF.

`chunking.group_units()` merges adjacent units into one chunk while they share the same
`heading_path` and `physical_page` and stay under `--max-chunk-chars` (default 1200) — so a chunk
never silently straddles a heading or page boundary. PDF chunks are page-local by design; a chunk spanning multiple pages never happens in the current implementation (plan 0006 only permits it when content genuinely spans pages, which this version does not yet detect).

## Markdown extraction

`parsers/markdown.py` parses `#`-`######` heading hierarchy and blank-line-delimited paragraphs.
Oversized paragraphs are further split on whitespace boundaries (`DEFAULT_MAX_UNIT_CHARS = 2400`)
so `chunking.group_units()` never has to split a single unit. `logical_key` is
`<heading-path>#<heading-occurrence>:p<paragraph-index>` (with a `:sub{n}` suffix for a split
oversized paragraph), robust to line-number shifts elsewhere in the document. A Markdown source
gets one synthetic `pages` row (`physical_page = 1`) holding the full document text and a
`layout_json` unit list, mirroring the PDF retained-extraction model.

## Physical-page retrieval

`tracecite page <source-path> [selector]` reads `pages.text` directly from SQLite—no search ranking or PDF reopening is involved. Omission selects physical page 1. A selector accepts a positive page, a closed range (`5-9`), an open range (`5-` or `-9`), or comma-separated combinations. Terms are expanded against indexed pages, deduplicated, and returned in ascending physical-page order. The standalone selector `all` selects every indexed page and cannot be combined with another term. TraceCite validates the complete selection before writing stdout, so a missing implied page cannot produce partial output.

Plain-text output for one selected page retains the original page command contract. Multiple pages have explicit physical-page delimiters. `--format json` always returns an ordered array; each element contains retained text, printed-label and extraction metadata, a `pdf_link`, one validated whole-page render or `null`, and validated figure-crop entries. Asset entries expose their database-relative identifier, validated local path, SHA-256, dimensions, labels, nearby text, and bounding box. Missing, escaped, or hash-mismatched assets fail before JSON is printed.

`tracecite extract-pages <source-path> [selector] --output-dir <dir>` uses the same selector grammar and page-1 omission default. Unlike `page`, it verifies and opens the indexed source PDF, writes only the normalized selected pages, and creates a provenance manifest. The existing output directory must be a real directory outside the source root. Source-hash mismatch, PDF/index page-count mismatch, overlap, symlinks, and existing outputs are rejected. The PDF and manifest are staged together and rolled back together after promotion failure; generated files remain caller-owned disposable runtime artifacts.

## Quotation verification

`tracecite verify quote <source-path> <physical-page> <quote>` checks, in order: (1) exact substring
match against `pages.text`; (2) a whitespace-normalised match (`chunking.normalise_text`: collapse
all whitespace, no case-folding) against the normalised page text; (3) otherwise `"not-found"`.
An empty quotation is `"structural-error"`. Only `exact` and `normalised` return process status
`0`; all other verification states return non-zero. This is intentionally independent of chunk
boundaries — a quotation may straddle two chunks.

## Report verification

`tracecite verify report <report.md> --root <dir> --database <db>` parses Markdown reference definitions whose destinations contain a local path plus `#page=<PAGE>` and inline citations (`[text][<label>]`). Labels are opaque. For every citation used in the body it checks: a matching definition exists; the definition's relative path resolves (relative to the report file's own directory) to an indexed source path; and the cited page is indexed. Blockquote lines (`> "..."`) are matched
only when the immediately associated prose paragraph resolves to exactly one viable citation label.
Ambiguous, missing, or empty quote associations are structural errors. Each quote result emits the
bound `citation_key` and resolved `source_path`, or `null` when no unique binding exists. Report
verification never writes to the report file — read-only, always.

When `--source-links docs/source-links.toml` is supplied, report verification additionally confirms every cited source path has exactly one schema-v3 registry entry keyed by `local_path`; it never edits the registry or the report. The `source-links.toml` schema is owned by `routing-documentation-source-links` and uses a `[[source]]` array of tables with `name`, `local_path`, `public_url`, and an opaque optional `metadata` table. Do not restore an obsolete placeholder registry shape.

## Assets

For every PDF page that gets (re)parsed, `sync._persist_assets()` writes one whole-page PNG render
(`pdf.render_page()`, via `page.get_pixmap()`) under `imgs/generations/<generation>/<source_pk>/page-{NNNN}.png`, plus one crop
per embedded raster image found on that page (`pdf.render_figure_crops()`, via
`page.get_images()`/`extract_image()`/`get_image_rects()`) to
`imgs/generations/<generation>/<source_pk>/page-{NNN}-image-{NN}.png`. New sources render into a same-generation staging directory and are atomically renamed to the assigned internal `source_pk` before asset rows are inserted. Both renders and crops are recorded in `assets` with their sha256,
dimensions, and (for crops) bounding box. **Limitation:** only embedded raster images are cropped;
a figure composed purely of vector graphics has no dedicated crop yet — use the whole-page render
for those until a fixture demonstrates the need for vector-composited crops. Assets live under `imgs/` next to the database (never inside SQLite); active database rows and `doctor` validate asset paths and hashes by internal key, not public source identity.

Page JSON and PDF search output resolve these existing asset rows only. Retrieval never regenerates a page render or crop and never treats an unchecked database path as a filesystem path.
