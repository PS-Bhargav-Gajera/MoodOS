---
tags: [moodos, tool, mcp]
---

# Search Movies

MCP tool `search_movies` → `MoodOSMCPServer.search_movies`
(`moodos/mcp_server.py:91`).

## Signature

`search_movies(query: str, watch_at_home: bool = False, language: str | None = None) -> list`

## Behavior

- Primary: `providers.search_movies_tmdb(query, watch_at_home, language)` ([[TMDB]]).
- Fallback: `knowledge.retrieve(query, k=6, kinds=["movie"])` — local RAG
  movie docs when TMDB returns nothing or no key is set
  (`mcp_server.py:94-95`, [[Knowledge RAG Store]]).

## Connects to

- [[TMDB]] · [[Knowledge RAG Store]]
- [[Movie Metadata and Mood Fit]]
- [[Derive Search Query]]

## Used by

- Public MCP surface (the plan path calls `suggest_movies` instead —
  `orchestrator.py:2167, 2170`; the bundle's `tool_usage.movies` label still
  names `search_movies`, `orchestrator.py:2362`)
- [[Route Prompts]] (exposure)