---
tags: [moodos, tool, mcp]
---

# Find Nearby Places

MCP tool `find_nearby_places` → `lambda lat, lon, q="cafe": providers.nearby_places(lat, lon, q)`
(`moodos/mcp_server.py:28`).

## Signature

`find_nearby_places(lat: float, lon: float, query: str = "cafe", limit: int = 8) -> list`

## Behavior

`providers.nearby_places` (`providers.py:132`) maps the query to an OSM amenity
(`cafe`/`restaurant`/`park`), queries **Overpass** first, falls back to
**Nominatim**, and caches 20 min. Built the same way as [[Search Restaurants]]
but not food-tiered.

In the pipeline it supplies the "places" (cafes/parks) leg of the item pool
(`orchestrator.py:1282`).

## Connects to

- [[OpenStreetMap]] · [[TTL Cache]]
- [[Search Restaurants]]

## Used by

- `run_pipeline` parallel tasks (`orchestrator.py:1282`)
- Public MCP surface