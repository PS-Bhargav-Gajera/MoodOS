---
tags: [moodos, route, api]
---

# Route Restaurants

`GET /api/restaurants?lat&lon&cuisine&mood&dietary&radius&limit` → `app.py:177`

## Behavior

- Defaults lat/lon to `settings.default_lat/lon` when absent (`app.py:187-188`).
- `mcp.call("search_restaurants", lat, lon, cuisine, mood, dietary, radius_m,
  limit)` ([[Search Restaurants]]) — mood branch when `mood` is present.
- Returns `{restaurants, count, lat, lon}`.

This is the **"Find restaurants" follow-up path** from the plan result card
(`app.js:523-535`). It is a second call site of the same provider used inside
the plan — the differences are documented in [[Find Restaurants button path]].

## Connects to

- [[Search Restaurants]] · [[Search Restaurants By Mood]] · [[OpenStreetMap]]

## Used by

- [[Frontend]] (`app.js:531`) · [[00-Home]]