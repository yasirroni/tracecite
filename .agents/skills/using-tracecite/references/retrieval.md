# Retrieval

## Hybrid search

```text
FTS5 BM25 top --fts-limit (default 50)
        +
SqliteVecBackend exact k-NN top --vector-limit (default 50)
        |
        v
reciprocal-rank fusion (k = 60), reduced to --limit (default 10)
```

`cli._search()` computes both candidate lists, fuses them by `score(chunk) = sum(1 / (60 + rank))` over whichever list(s) contain that chunk, then returns the top `--limit` chunks (configurable 10-20 is the practical default; both `--fts-limit`
and `--vector-limit` are independently configurable). Each result reports `rank`, `source_path`, `source_type`, `source_sha256`, `heading_path`, `passage` (`body`), `physical_page`, `page_offsets`, `page_range`, `line_range`, `locator`, `content_type`, `provenance` (`["lexical"]`, `["vector"]`, or both), and `fused_score`. PDF results for a physical page also include a ready-to-use `pdf_link` of the form `<source-path>#page=<N>`, a validated `page_render`, and zero or more validated `figure_crops`. Results without a PDF physical page use `null` for `page_render` and an empty list for `figure_crops`. Internal `chunk_id`, `source_pk`, page IDs, and asset IDs are not part of the result contract. Fused scores are relative ranking signals, not calibrated probabilities; never present them as absolute semantic confidence.

## Query recovery

The query is passed unchanged to vector embedding. Valid raw FTS5 `MATCH` expressions—quoted phrases, operators, and prefix expressions—retain their lexical behavior. If FTS5 reports its lexical syntax error, TraceCite emits a diagnostic on stderr and retries only the lexical half with the query quoted as a phrase. This permits ordinary punctuation-heavy text such as `10%, 50%, and 90%` to continue through hybrid retrieval without contaminating JSON stdout. Other SQLite errors propagate unchanged; the fallback is not a general query sanitizer.

Search results are for discovery. For PDFs, inspect `source_path`, retrieve the full physical page or neighbouring page selection with `tracecite page`, and use JSON page output to locate indexed page renders and figure crops when layout matters. Create a selected-page derivative with `tracecite extract-pages` only when the inspection tool requires PDF input. Use `tracecite verify quote` before treating wording as an exact or normalised quotation. A physical page number is the PDF page identity and may differ from the printed label.

For workbooks, inspect `source_sha256`, `locator.sheet`, and `locator.exact_ranges` in the authoritative workbook. `locator.range` is a bounding rectangle rather than a claim that every enclosed cell contributed to the result. Workbook search does not create a portable browser deep link or independently verify a displayed Excel rendering. Rank, fused score, Markdown hits, workbook hits, and a failed verification do not establish external-source proof.

Vector search is scoped to the **active** embedding model only: `_search()` restricts
`allowed_embedding_ids` to `embeddings` rows whose `model_id` matches the current `kb_config`, so a
retained-but-inactive older model's vectors never leak into ranking.

## No ANN index

There is no approximate-nearest-neighbour index. `SqliteVecBackend.search()` always runs an exact `vec0` k-NN scan (`k` = every row when a bounded filter is supplied, since a smaller `k` could silently miss an allowed id that ranks outside it — filtering to the allowed set happens in Python afterward). Add quantisation, pre-filtering, or an ANN structure only after a measured retrieval-quality/latency need on a real corpus, not speculatively.

## Metadata filters

`SqliteVecBackend.search(conn, query_vector, top_k, allowed_embedding_ids=...)` is the seam for
bounded filtering (e.g. restrict to a source, page range, or content type) — resolve the allowed
`embedding_id` set with an ordinary SQL join over `chunks`/`chunk_embeddings`/`embeddings`, then pass
it through. Do not add vec0-specific partition/auxiliary-column SQL outside `vector_backend.py`.

## Exact terms

FTS5's `unicode61` tokenizer preserves exact identifiers, numbers, and acronyms in the lexical
half of retrieval; do not rely on the vector half alone for exact-wording queries (`tracecite verify quote`
and `tracecite verify report` intentionally bypass ranked search entirely and check the retained `pages.text`
directly — see `references/pdf-and-assets.md`).
