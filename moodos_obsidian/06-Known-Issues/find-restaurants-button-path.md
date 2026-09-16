---
tags: [moodos, known-issue, bug, frontend]
---

# Find Restaurants button path

**Reported**: the "Find restaurants" follow-up button uses a different search
path than the main bundler and sometimes fails when the bundler succeeds.

## The two call sites (verified)

| | Main plan (bundler) | "Find restaurants" button |
|---|---|---|
| Frontend | — | `app.js:523-535`, fires after a plan renders |
| HTTP | none (in-process) | `GET /api/restaurants` ([[Route Restaurants]], `app.py:177`) |
| Tool | `mcp.call("search_restaurants", mood=...)` (`orchestrator.py:1268-1273`) | `mcp.call("search_restaurants", ...)` (`app.py:189`) |
| Limit | `8` | `10` |
| Parameter source | `restaurant_mood` from slots (`orchestrator.py:1256`) | `data.slots.desired_mood \|\| current_mood` re-read from the **bundle** (`app.js:525`) |
| Location | resolved lat/lon of the plan | `geo.lat` if GPS live, **else nothing** → server uses `settings.default_lat/lon` (Ahmedabad) |

## Why it can diverge

1. **Different location when no live GPS**: the plan can be built for a typed
   city (user_label → geocode) or IP location; the button only sends
   `geo.lat/lon` and, when GPS is off, silently searches the **default city**
   (`app.py:187-188`). So "plan for Mumbai" + "find restaurants" → Ahmedabad
   results. (Reported symptom often matches this.)
2. **Mood string mismatch**: the button uses `desired_mood || current_mood`
   from the bundle; the bundler passes `desired_mood || current_mood` from
   slots — normally equal, but wording can differ after an LLM slot merge.
   When the button's mood is empty but the plan used one, the generic
   `nearby_restaurants` path runs instead of the mood→cuisine path
   ([[Search Restaurants By Mood]]).
3. **Duplicate network call**: `search_restaurants_by_mood` runs up to 2
   cuisine OSM queries + a generic fallback (`providers.py:477-498`). Inside
   the bundler this runs under ThreadPoolExecutor alongside everything else; on
   the button it's a cold, sequential path that can hit OSM timeouts/empty
   results ([[OpenStreetMap]], 18 s timeout) → "No restaurants found nearby."
4. Results are **uncached between the two** only when inputs differ (cache key
   includes lat/lon/cuisine/radius — [[TTL Cache]]).

## Impact

User trusts the plan's restaurants, clicks the button, and gets an unrelated
or empty list.

## Suggested fix (not yet implemented)

- Make the button reuse the bundle's resolved location (pass the plan's
  `city`/lat/lon through to `/api/restaurants`) instead of `geo`/defaults.
- Reuse the exact mood token the bundler used (persist `restaurant_mood` in
  the bundle).
- Reuse the same `limit` and share one cache key shape.

## Connects to

- [[Search Restaurants]] · [[Route Restaurants]] · [[Location Resolution]]
- [[Frontend]] · [[TTL Cache]]

## Used by

- [[00-Home]]