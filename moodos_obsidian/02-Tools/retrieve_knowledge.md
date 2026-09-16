---
tags: [moodos, tool, mcp]
---

# Retrieve Knowledge

MCP tool `retrieve_knowledge` → `lambda q, k=8: knowledge.retrieve(q, k)`
(`moodos/mcp_server.py:30`).

## Signature

`retrieve_knowledge(query: str, k: int = 8) -> list` (plus confidence score).

## Behavior

Calls `KnowledgeStore.retrieve` (`rag.py:48`) — TF-IDF cosine retrieval over
`seed_knowledge.json` + `acquired_knowledge.json` ([[Knowledge RAG Store]]).
Returns `(hits, confidence)`. When no docs are loaded, returns `([], 0.0)`.

**Note**: `run_pipeline` calls `knowledge.retrieve` **directly**
(`orchestrator.py:1233`) rather than through this MCP wrapper; the tool exists
for external clients. The pipeline uses a confidence threshold of `0.12` to
decide whether to do web fallback ([[Fallbacks and Degradation]]).

## Connects to

- [[Knowledge RAG Store]] · [[TTL Cache]]

## Used by

- Public MCP surface
- [[Request Flow]] (equivalent direct call)