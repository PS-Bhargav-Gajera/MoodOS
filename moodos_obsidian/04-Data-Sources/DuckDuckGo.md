---
tags: [moodos, data-source, provider]
---

# DuckDuckGo

Free web search via the `ddgs` package — the knowledge web fallback.

## Source

`providers.web_snippets(query, limit=4)` (`providers.py:1329`):
`DDGS().text(query, max_results=limit)`. Returns `title`, `text` (the DDGS
body), `url` (the DDGS href) + `id`, as `kind: web`, `source: duckduckgo`.
Cached 2 h.

Used in the **adaptive fallback** when RAG confidence < 0.12: the pipeline
searches for "`{city}` quiet cafe relaxing evening", ingests the top-3 snippets
into the knowledge store, and retries retrieval (`orchestrator.py:2223-2239`,
threshold at `orchestrator.py:2125`, [[Fallbacks and Degradation]]).

## Connects to

- [[Search Web Knowledge]] · [[Knowledge RAG Store]] · [[TTL Cache]]

## Used by

- [[Request Flow]] · [[Fallbacks and Degradation]]