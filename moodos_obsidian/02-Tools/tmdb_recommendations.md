---
tags: [moodos, tool, mcp]
---

# Tmdb Recommendations

MCP tool `tmdb_recommendations` → `lambda tmdb_id, limit=6: providers.tmdb_recommendations(tmdb_id, limit)`
(`moodos/mcp_server.py:41`).

## Signature

`tmdb_recommendations(tmdb_id: int, limit: int = 6) -> list`

## Behavior

`/movie/{id}/recommendations` — "more like this" (`providers.py:1055`).
Returns `kind: movie`, `watch_at_home: True`, `subtype: streaming`, default
runtime 130 min. Cached 12 h. No key → `[]`.

Currently exposed as a public tool but **not invoked** by the live plan path.

## Connects to

- [[TMDB]] · [[Search Home Movies]] · [[TTL Cache]]

## Used by

- Public MCP surface
- [[Route Prompts]] (exposure)