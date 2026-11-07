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

`commands.hybrid_search()` fuses the two candidate lists with `score(chunk) = sum(1 / (60 + rank))` over the lists that contain the chunk. Equal scores rank the shorter path first, then sort order. `--lexical-only` skips the vector list and the embedding model. `--source-type` restricts both lists. The vector list uses only embeddings of the database's model.

`search` prints a JSON array. Each result has `rank`, `source_path`, `source_type`, `source_sha256`, `heading_path`, `passage`, `physical_page`, `page_offsets`, `page_range`, `line_range`, `locator`, `content_type`, `provenance` (`["lexical"]`, `["vector"]`, or both), `fused_score`, and `duplicate_paths`. Byte-identical files yield identical chunks, so each passage is reported once under its best-ranked path, and the other paths go in `duplicate_paths`. A PDF result with a physical page also has `pdf_link` (`<source-path>#page=<N>`), a validated `page_render`, and zero or more validated `figure_crops`. Other results have `page_render: null` and an empty `figure_crops`. Internal `chunk_id`, `source_pk`, page IDs, and asset IDs are not part of the result. `fused_score` ranks results relative to each other; it is not a calibrated probability, so never present it as semantic confidence.

## Query recovery

Valid FTS5 `MATCH` syntax, such as quoted phrases, `OR`, `NOT`, and prefixes like `retire*`, keeps its lexical behaviour. When FTS5 cannot parse the query, for example `de-rating`, `heat: wind`, `10%`, or an unbalanced quote, TraceCite says so on stderr and runs lexical search again with each whitespace-separated word quoted. A result must then contain every word, and any operators in the query are ignored. Database errors still propagate.

The embedding model is English-only. Vector search drops CJK text from the query and says so on stderr; a query with only CJK text uses lexical search only. When FTS5 returns fewer than `--fts-limit` rows for a query with CJK text, lexical search adds chunks whose text contains every CJK run. That substring scan reads every chunk, so it is slower on a large database.

## No ANN index

There is no approximate-nearest-neighbour index. `SqliteVecBackend.search()` runs exact `vec0` k-NN queries and applies allowed-ID filters before ranking. Each shard returns at most `top_k` candidates, within sqlite-vec's per-query limit, and Python selects the global nearest results. Filtering after truncation would silently miss eligible vectors. Add quantisation or an ANN structure only after a measured retrieval-quality or latency need on a real corpus.

## Metadata filters

`SqliteVecBackend.search(conn, query_vector, top_k, allowed_embedding_ids=...)` is where bounded filtering goes, for example by source, page range, or content type. Resolve the allowed `embedding_id` set with an ordinary SQL join over `chunks`, `chunk_embeddings`, and `embeddings`, then pass it in. Do not write vec0 partition or auxiliary-column SQL outside `vector_backend.py`.

## Exact terms

The FTS5 `unicode61` tokenizer keeps exact identifiers, numbers, and acronyms in the lexical half of retrieval, so do not rely on the vector half alone for exact wording. `verify quote` and `verify report` bypass ranked search and check the retained `pages.text` directly; see `references/pdf-and-assets.md`.
