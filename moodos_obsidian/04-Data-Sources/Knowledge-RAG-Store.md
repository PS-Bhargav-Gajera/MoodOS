---
tags: [moodos, data-source, rag, storage]
---

# Knowledge RAG Store

Local domain knowledge: TF-IDF retrieval over JSON docs — zero API cost.

## Files

- `data/seed_knowledge.json` — seed docs (kind/text/themes/moods).
- `data/acquired_knowledge.json` — docs ingested from web
  (`source: "web-acquisition"` or `web:` ids), written only on insert/update
  (`rag.py:83-84`).

## Source

`KnowledgeStore` (`rag.py:16`):
- Loads both files on start (`load_seed`), refits the TF-IDF matrix.
- `retrieve(query, k, kinds)` (`rag.py:48`) → `(hits, confidence)`, where
  confidence = the top cosine score.
- `ingest(doc)` (`rag.py:67`) → insert/update/ignore, refit, persist acquired
  docs, and `log_knowledge` the action ([[Local SQLite]]).

## Pipeline usage

- Retrieval with a mood-tuned query and `rag_conf >= 0.12` gate
  (`orchestrator.py:1226-1236`).
- Below threshold → [[DuckDuckGo]] web snippets are ingested then retrieval
  retried ([[Fallbacks and Degradation]]).
- Movies: RAG is the fallback when TMDB returns nothing ([[Search Movies]]).

## Connects to

- [[Retrieve Knowledge]] · [[Search Web Knowledge]] · [[DuckDuckGo]] · [[Local SQLite]]
- [[Fallbacks and Degradation]] · [[Persistence]]

## Used by

- [[Request Flow]] · [[Architecture-Overview]]