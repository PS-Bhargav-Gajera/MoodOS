---
tags: [moodos, tool, mcp]
---

# Tmdb Watch Providers

MCP tool `tmdb_watch_providers` → `lambda tmdb_id, region="IN": providers.tmdb_watch_providers(tmdb_id, region)`
(`moodos/mcp_server.py:42`).

## Signature

`tmdb_watch_providers(tmdb_id: int, region: str = "IN") -> dict`

## Behavior

`/movie/{id}/watch/providers` (region-aware): returns `flatrate`, `rent`, `buy`
listings + a `link` for OTT availability in the given region
(`providers.py:1238`). Cached 12 h (only when the region has data). Default
region is `IN` (Indian streamers like Prime/Netflix/Hotstar appear in
`flatrate`).

Used by [[Search Home Movies]] to build the "watch at home" cards.

## Connects to

- [[TMDB]] · [[Search Home Movies]] · [[TTL Cache]]

## Used by

- [[Search Home Movies]] (`mcp_server.py:127`)
- Public MCP surface