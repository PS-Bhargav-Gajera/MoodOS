---
tags: [moodos, tool, mcp]
---

# Search Restaurants

MCP tool `search_restaurants` → `MoodOSMCPServer.search_restaurants`
(`moodos/mcp_server.py:115`).

## Signature

`search_restaurants(lat, lon, cuisine=None, mood=None, dietary=None, radius_m=5000, limit=10) -> list`

## Behavior

- If `mood` is truthy → `providers.search_restaurants_by_mood` (mood→cuisine
  map, see [[Search Restaurants By Mood]]).
- Else → `providers.nearby_restaurants` (generic OSM food search).
- Both travel through Overpass/Nominatim ([[OpenStreetMap]]) and are cached.

This is the provider behind both the main plan (mood path via
`orchestrator.py:1266-1273`) **and** the "Find restaurants" follow-up button
(`GET /api/restaurants`, [[Route Restaurants]]). The two call sites are subtly
different — see [[Find Restaurants button path]].

## Connects to

- [[OpenStreetMap]] · [[Search Restaurants By Mood]] · [[TTL Cache]]
- [[Route Restaurants]]

## Used by

- `run_pipeline._restaurants` (`orchestrator.py:1266`)
- `GET /api/restaurants` (`app.py:189`)
- Public MCP surface