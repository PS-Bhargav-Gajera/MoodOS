---
tags: [moodos, tool, mcp]
---

# Find Nearby Cinemas

MCP tool `find_nearby_cinemas` → `lambda lat, lon, limit=6: providers.nearby_cinemas(lat, lon, limit)`
(`moodos/mcp_server.py:29`).

## Signature

`find_nearby_cinemas(lat: float, lon: float, limit: int = 6) -> list`

## Behavior

`providers.nearby_cinemas` (`providers.py:157`) queries Overpass for
`amenity=cinema` within 15 km, wrapped in a 24 h cache. Each venue is a
`kind:movie` candidate with `has_venue: True`, default cost ₹250 / 140 min.
The mock *showtimes* are attached later in [[Movie Candidates]] (real cinema +
canned show title/time from `actions.py`).

Skipped entirely for stay-home plans (`orchestrator.py:1275-1278`).

## Connects to

- [[OpenStreetMap]] · [[TTL Cache]]
- [[Movie Candidates]] · [[Movie Metadata and Mood Fit]]

## Used by

- `run_pipeline._cinemas` (`orchestrator.py:1275`)
- Public MCP surface