---
title: "Search an Excel workbook with vectors"
---

TraceCite can index stored worksheet content from `.xlsx` and `.xlsm` files and retrieve candidate evidence through lexical and semantic search.
This example uses AEMO's 2023 Electric Vehicle workbook because its separate weekday and weekend charging-profile worksheets provide a clear semantic retrieval case.

## Source workbook

**Workbook:** [local copy](../assets/workbooks/2023-iasr-ev-workbook.xlsx) · [AEMO online copy](https://www.aemo.com.au/-/media/files/major-publications/isp/2023/2023-iasr-ev-workbook.xlsx?rev=d600796546d4448ba2d647643e248d8c&sc_lang=en)

**Indexed local file SHA-256:** `5fb01b7eb8861d20a50d02628fdb686bae83f7f046a5288f2f62cb27126eb246`

Both links open the workbook as a file.
The worksheet and A1-range locators returned by TraceCite identify the relevant evidence; a generic workbook URL does not encode those locators.
The SHA-256 above identifies the bundled local copy used for this example and should be recalculated before assuming that a separately downloaded copy is byte-identical.

## Synchronise the workbook

The demonstrated run used `sentence-transformers/all-MiniLM-L6-v2` and a maximum chunk size of 2,400 characters.
The model must already be present in the selected cache or be available for download.

```sh
mkdir -p .tracecite

cat > .tracecite/workbook-example.toml <<'TOML'
schema_version = 1

[[source]]
path = "2023-iasr-ev-workbook.xlsx"
TOML

tracecite sync \
  --root docs/assets/workbooks \
  --manifest .tracecite/workbook-example.toml \
  --database .tracecite/workbook-example.sqlite \
  --model-cache-dir .tracecite/model-cache \
  --max-chunk-chars 2400

tracecite doctor --database .tracecite/workbook-example.sqlite
```

The run indexed ten worksheets as 616 retrieval chunks and generated 616 embeddings.
The integrity check reported no issues.

## Run a semantic query

The query describes the subject rather than copying a workbook phrase:

```sh
tracecite search \
  "weekday versus weekend electric vehicle charging behaviour" \
  --database .tracecite/workbook-example.sqlite \
  --model-cache-dir .tracecite/model-cache \
  --limit 5
```

The two highest-ranked results were retrieved through the vector index:

| Rank | Worksheet | Bounding range | Exact contributing ranges | Retrieval |
|---:|---|---|---|---|
| 1 | `BEV_PHEV_Profile_kW (Weekend)` | `B2:AT9` | `B2`, `B3`, `B4`, `B5`, `B8`, `C9:AT9` | vector |
| 2 | `BEV_PHEV_Profile_kW (Weekday)` | `B2:AT8` | `B2`, `B3`, `B4`, `B5`, `B7`, `C8:AT8` | vector |

`vector` provenance means that semantic retrieval contributed the result while lexical FTS did not contribute it to this ranking.
The bounding range is a convenient envelope; only the listed exact ranges contributed to the indexed passage.

## Cite the workbook evidence

A defensible citation keeps the workbook identity and the evidence locator together:

> AEMO, *2023 Electric Vehicle workbook*, sheets `BEV_PHEV_Profile_kW (Weekend)` and `BEV_PHEV_Profile_kW (Weekday)`, exact ranges `B2`, `B3`, `B4`, `B5`, `B8`, `C9:AT9` and `B2`, `B3`, `B4`, `B5`, `B7`, `C8:AT8` ([local workbook](../assets/workbooks/2023-iasr-ev-workbook.xlsx); [online workbook](https://www.aemo.com.au/-/media/files/major-publications/isp/2023/2023-iasr-ev-workbook.xlsx?rev=d600796546d4448ba2d647643e248d8c&sc_lang=en)).

The links provide local and official online access to the source workbook.
The worksheet names, exact A1 ranges, and local file hash provide the evidence identity that the workbook links themselves cannot express portably.

## Evidence boundary

Search rank identifies candidate evidence rather than proving a claim on its own.
Inspect the returned cells in the workbook before relying on them, and record whether a formula, cached value, or literal stored value supports the interpretation.