---
tags: [moodos, tool, mcp]
---

# Tmdb Trending

MCP tool `tmdb_trending` → `lambda media_type="movie", time_window="week", limit=8: providers.tmdb_trending(media_type, time_window, limit)`
(`moodos/mcp_server.py:43`).

## Signature

`tmdb_trending(media_type: str = "movie", time_window: str = "week", limit: int = 8) -> list`

## Behavior

`/trending/{media_type}/{time_window}` (`providers.py:1268`). Returns
`kind: movie|tv`, all marked `watch_at_home: True` (live), `subtype: streaming`,
default runtime 120 min. Cached 6 h. No key → `[]`.

Used by [[Search Home Movies]] as a fallback when the search yields < 4 results
(`mcp_server.py:117-122`).

## Connects to

- [[TMDB]] · [[Search Home Movies]] · [[TTL Cache]]

## Used by

- [[Search Home Movies]]
- Public MCP surface