---
tags: [moodos, tool, mcp]
---

# Find Nearby Cinemas

MCP tool `find_nearby_cinemas` → `lambda lat, lon, limit=6: providers.nearby_cinemas(lat, lon, limit)`
(`moodos/mcp_server.py:32`).

## Signature

`find_nearby_cinemas(lat: float, lon: float, limit: int = 6) -> list`

## Behavior

`providers.nearby_cinemas` (`providers.py:365`) finds real cinema/theatre
venues via `location_service.search_nearby_places(categories="cinema",
radius_m=15000, limit=limit)` — a single Overpass query cached 30 min
(`location_service.py:247`, [[TTL Cache]]). Each venue is a `kind: movie`
candidate with `has_venue: True`, default cost ₹250 / 140 min, `review_quality`
7.0. The mock *showtimes* are attached later in [[Movie Candidates]] (real
cinema + estimated show title/time from `actions.list_showtimes`,
`orchestrator.py:263-296`).

Skipped entirely for stay-home plans (`_cinemas` → `[]`,
`orchestrator.py:2183-2186`).

## Connects to

- [[OpenStreetMap]] · [[TTL Cache]]
- [[Movie Candidates]] · [[Movie Metadata and Mood Fit]]

## Used by

- `run_pipeline._cinemas` (`orchestrator.py:2186`)
- Public MCP surface
