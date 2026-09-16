---
tags: [moodos, tool, mcp]
---

# Search Home Movies

MCP tool `search_home_movies` → `MoodOSMCPServer.search_home_movies`
(`moodos/mcp_server.py:93`).

## Signature

`search_home_movies(query: str, limit: int = 8) -> list`

## Behavior

- `providers.search_movies_tmdb(query=..., limit=limit, watch_at_home=True)`
  ([[TMDB]], `providers.py:789`).
- If fewer than 4 results, appends **trending** movies
  (`tmdb_trending`, `providers.py:1019`) not already present.
- Enriches the top 4 with streaming availability via
  `tmdb_watch_providers` ([[TMDB]], `providers.py:985`): attaches `streaming`
  (flatrate or rent, first 3) and `watch_link`.

Used for **stay-home** plans only (`run_pipeline._movies`, `orchestrator.py:1261-1263`);
their plan steps carry `kind: streaming` ([[Home vs Out Mode]]).

## Connects to

- [[TMDB]] · [[Home vs Out Mode]] · [[Movie Metadata and Mood Fit]]

## Used by

- `run_pipeline._movies` stay-home branch (`orchestrator.py:1261`)
- Public MCP surface