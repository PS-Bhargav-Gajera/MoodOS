---
tags: [moodos, known-issue, bug, frontend]
---

# Find Restaurants button path

**Reported**: the "Find restaurants" follow-up button uses a different search
path than the main bundler and sometimes fails when the bundler succeeds.

## The two call sites (verified)

| | Main plan (bundler) | "Find restaurants" button |
|---|---|---|
| Frontend | — | `app.js:635-650`, attached when a plan renders (button markup `:498`) |
| HTTP | none (in-process) | `GET /api/restaurants` ([[Route Restaurants]], `app.py:439`) |
| Tool | `mcp.call("search_restaurants", mood=...)` (`orchestrator.py:2174-2181`) | `mcp.call("search_restaurants", ...)` (`app.py:451-460`) |
| Limit | `8` (`orchestrator.py:2180`) | `8`, sent explicitly (`app.js:642`; server default is `10`, `app.py:447`) |
| Parameter source | `restaurant_mood` from slots (`orchestrator.py:2156`) | `data.slots.desired_mood \|\| current_mood` re-read from the **bundle** (`app.js:637`) |
| Location | resolved lat/lon of the plan | `geo.lat` if GPS live, **else nothing** → server uses `settings.default_lat/lon` (Ahmedabad) |

## Why it can diverge

1. **Different location when no live GPS**: the plan can be built for a typed
   city (user_label → geocode) or IP location — `resolveLocation()` never
   writes into `geo.lat/lon` (`app.js:122-141`) — while the button only sends
   `geo.lat/lon` and, when GPS is off, silently searches the **default city**
   (`app.py:449-450`). So "plan for Mumbai" + "find restaurants" → Ahmedabad
   results. (Reported symptom often matches this.)
2. **Mood string**: the button uses `desired_mood || current_mood` from the
   bundle and the bundler uses the same expression from slots
   (`orchestrator.py:2156`), so the two normally agree now (casing is
   normalized in `providers.search_restaurants_by_mood`, `providers.py:658`).
   The residual case is an *empty* mood on both sides: the generic
   `nearby_restaurants` path runs instead of the mood→cuisine path
   (`mcp_server.py:145-151`, [[Search Restaurants By Mood]]).
3. **Duplicate network call**: `search_restaurants_by_mood` runs up to 2
   cuisine OSM queries + a generic fallback (`providers.py:667-690`). Inside
   the bundler this runs under ThreadPoolExecutor alongside everything else
   (`orchestrator.py:2197-2208`); on the button it's a cold, sequential path
   that can still hit OSM's bounded failure path ([[OpenStreetMap]], 12 s
   wall-clock budget + circuit breaker, `providers.py:225-279`) → "No
   restaurants found nearby."
4. Results are **uncached between the two** only when inputs differ (cache key
   includes lat/lon/cuisine/radius — `providers.py:545`, [[TTL Cache]]).

## Impact

User trusts the plan's restaurants, clicks the button, and gets an unrelated
or empty list.

## Suggested fix (not yet implemented)

- Make the button reuse the bundle's resolved location (pass the plan's
  `city`/lat/lon through to `/api/restaurants`) instead of `geo`/defaults.
- Reuse the exact mood token the bundler used (persist `restaurant_mood` in
  the bundle).
- `limit` already matches (both send 8); the cache keys still diverge whenever
  the location inputs differ — sharing the resolved location would fix both.

## Connects to

- [[Search Restaurants]] · [[Route Restaurants]] · [[Location Resolution]]
- [[Frontend]] · [[TTL Cache]]

## Used by

- [[00-Home]]