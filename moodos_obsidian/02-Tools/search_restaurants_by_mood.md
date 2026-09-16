---
tags: [moodos, tool, mcp]
---

# Search Restaurants By Mood

MCP tool `search_restaurants_by_mood` → `MoodOSMCPServer.search_restaurants_by_mood`
(`moodos/mcp_server.py:134`).

## Signature

`search_restaurants_by_mood(lat, lon, mood, dietary=None, radius_m=5000, limit=10) -> list`

## Behavior

Maps a mood string to cuisines via `MOOD_CUISINE_MAP` (`providers.py:208`),
e.g. `calm` → `tea/bakery/coffee_shop`, `celebratory` → fine dining, `date` →
italian/french. Searches the first 2 cuisines via
`nearby_restaurants` (5 each), then fills remaining slots with generic nearby
restaurants (`providers.py:459-500`). Results are tagged `mood_match` +
`mood_vibe`.

Unknown mood → falls back to the `happy` mapping (`providers.py:469`).

## Connects to

- [[OpenStreetMap]] · [[Search Restaurants]]
- [[Intent and Mood Extraction]] (mood source)

## Used by

- [[Search Restaurants]] (mood branch)
- `run_pipeline._restaurants` when a mood is set
- [[Route Restaurants]] when `?mood=` is passed