---
tags: [moodos, tool, mcp]
---

# Search Home Movies

MCP tool `search_home_movies` → `MoodOSMCPServer.search_home_movies`
(`moodos/mcp_server.py:111`).

## Signature

`search_home_movies(query: str, limit: int = 8, language: str | None = None) -> list`

## Behavior

- `providers.search_movies_tmdb(query=..., limit=limit, watch_at_home=True,
  language=language)` ([[TMDB]], `providers.py:979`).
- If fewer than 4 results, appends **trending** movies
  (`tmdb_trending`, `providers.py:1268`) not already present.
- Enriches the top 4 with streaming availability via
  `tmdb_watch_providers` ([[TMDB]], `providers.py:1238`): attaches `streaming`
  (flatrate or rent, first 3) and `watch_link`.

Used for **stay-home** plans only (`run_pipeline._movies`, `orchestrator.py:2163-2169`);
their plan steps carry `kind: streaming` ([[Home vs Out Mode]]).

## Connects to

- [[TMDB]] · [[Home vs Out Mode]] · [[Movie Metadata and Mood Fit]]

## Used by

- `run_pipeline._movies` stay-home branch (`orchestrator.py:2167`)
- Public MCP surface