---
tags: [moodos, tool, mcp]
---

# Search Movies

MCP tool `search_movies` → `MoodOSMCPServer.search_movies`
(`moodos/mcp_server.py:88`).

## Signature

`search_movies(query: str, watch_at_home: bool = False) -> list`

## Behavior

- Primary: `providers.search_movies_tmdb(query, watch_at_home)` ([[TMDB]]).
- Fallback: `knowledge.retrieve(query, k=6, kinds=["movie"])` — local RAG
  movie docs when TMDB returns nothing or no key is set
  (`mcp_server.py:90-91`, [[Knowledge RAG Store]]).

## Connects to

- [[TMDB]] · [[Knowledge RAG Store]]
- [[Movie Metadata and Mood Fit]]
- [[Derive Search Query]]

## Used by

- `run_pipeline._movies` (`orchestrator.py:1260-1264`) — the going-out movie path
- [[Route Prompts]] (exposure)