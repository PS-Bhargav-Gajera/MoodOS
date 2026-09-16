---
tags: [moodos, tool, mcp]
---

# Search Web Knowledge

MCP tool `search_web_knowledge` → `lambda q: providers.web_snippets(q)`
(`moodos/mcp_server.py:31`).

## Signature

`search_web_knowledge(query: str, limit: int = 4) -> list`

## Behavior

`providers.web_snippets` (`providers.py:1090`) — DuckDuckGo text search via the
`ddgs` package ([[DuckDuckGo]]). Cached 2 h.

Used by the **adaptive fallback**: when RAG confidence < 0.12, the pipeline
searches the web for the city + "quiet cafe relaxing evening", ingests the top-3
snippets into the knowledge store, and retries retrieval
(`orchestrator.py:1313-1326`, [[Fallbacks and Degradation]]).

## Connects to

- [[DuckDuckGo]] · [[Knowledge RAG Store]] · [[TTL Cache]]

## Used by

- `run_pipeline` adaptive fallback (`orchestrator.py:1315`)
- Public MCP surface