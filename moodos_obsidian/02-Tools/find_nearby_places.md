---
tags: [moodos, tool, mcp]
---

# Find Nearby Places

MCP tool `find_nearby_places` → `lambda lat, lon, q=None, limit=24, radius_m=4000: location_service.search_nearby_places(lat, lon, categories=q, limit=limit, radius_m=radius_m)`
(`moodos/mcp_server.py:30`).

## Signature

`find_nearby_places(lat: float, lon: float, q: str | None = None, limit: int = 24, radius_m: int = 4000) -> list`

## Behavior

`location_service.search_nearby_places` (`location_service.py:213`) — one
**Overpass** query for the requested categories (radius clamped 800–20000 m,
limit 1–60), normalized + deduped + distance-sorted, with route times
attached. No Overpass match → honest empty list, never fabricated venues.
Cached 30 min when populated / 3 min when empty (`location_service.py:247`,
[[TTL Cache]]).

`q=None` (the pipeline default) resolves to **all** categories (`_parse_categories`,
`location_service.py:100`): cafe, restaurant, fast_food, dessert, walk, cinema,
museum, attraction, shopping, bookstore, entertainment, wellness.

In the pipeline it supplies the "places" (cafes/parks) leg of the item pool
(`orchestrator.py:2189`, called with `q=None`).

## Connects to

- [[OpenStreetMap]] · [[TTL Cache]]
- [[Search Restaurants]]

## Used by

- `run_pipeline` parallel tasks (`orchestrator.py:2189`)
- Public MCP surface
