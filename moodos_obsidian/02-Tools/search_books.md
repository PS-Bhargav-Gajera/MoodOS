---
tags: [moodos, tool, mcp]
---

# Search Books

MCP tool `search_books` → `lambda q: providers.search_books(q)`
(`moodos/mcp_server.py:23`).

## Signature

`search_books(query: str, limit: int = 5) -> list`

## Behavior

Calls `providers.search_books` (`providers.py:618`) — Google Books API query
(`https://www.googleapis.com/books/v1/volumes`). Items carry `title`,
`text` (first 600 chars of description), `themes` (categories). Cached 6 h.

In the pipeline the music/books query is fixed at `"comfort quiet
contemporary"` (`orchestrator.py:1284`).

## Connects to

- [[Google-Books]]
- [[TTL Cache]]

## Used by

- `run_pipeline` parallel tasks (`orchestrator.py:1284`)
- Public MCP surface