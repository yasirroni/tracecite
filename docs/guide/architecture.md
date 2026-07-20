---
title: "Architecture"
---

## File roles

| File or artefact | Primary consumer | Role | Edited directly? |
|---|---|---|---:|
| `.py` / `.jl` | Humans and agents | Executable analysis, narrative, and generation logic | Yes |
| retained `.md` | Agents, grep, FTS, table parser | Executed evidence with original tables | No |
| `.ipynb` | Humans | Optional interactive projection of Python source | Usually synchronised |
| `.html` | Humans | Polished browsing interface | No |
| embedding Markdown copy | Auditors and developers | Raw tables plus derived retrieval text | No |
| future SQLite/vector index | Agents and applications | Rebuildable retrieval cache | No |

: TraceCite file roles and authority. {#tbl-file-roles}

## Authority chain

```text
input data
   -> executable page (.py or .jl)
   -> retained Pandoc Markdown
      -> human HTML
      -> TraceCite canonical table model
         -> normalised retrieval text
         -> diagnostics
         -> optional inspection site
```

TraceCite does not infer analytical meaning that the source does not state. It preserves captions, column labels, explicit units, rank, ordering metadata, and section context. It does not guess Celsius from a plausible temperature or infer that the first numeric row is a maximum.

Configured row identity is also separated from display order. An observation can move from rank 2 to rank 1 while keeping the same deterministic row identifier, allowing a future indexer to update the record rather than treating it as unrelated evidence.

## Why raw tables remain

The raw table remains useful evidence. An agent can inspect column alignment, missing cells, duplicate ranks, inconsistent units, impossible values, and whether the normaliser itself introduced an error. The derived representation is easier to retrieve, but it is not treated as independent evidence.

## Literate and Documenter

Literate-generated Markdown may contain an HTML MIME table rather than a native pipe table. TraceCite stores the HTML unchanged, converts it to canonical Markdown, and sends that canonical table through the same normaliser used by Quarto output.
