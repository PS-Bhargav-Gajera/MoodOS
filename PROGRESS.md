# MoodOS fix log
## Rules for every run
- Read this file first. Do ONE step only, update the log, then STOP.
- Your output limit is small: never rewrite whole files. Make small patches to only the lines needed.
- Do not change tool names, function signatures or return shapes. Do not touch data/*.
- After the edit, run the step's quick check and paste the raw result into this log.
- If a check fails twice, write "BLOCKED: <error>" here and stop.
## Diagnosed cause (do not re-investigate)
find_nearby_places, search_restaurants and find_nearby_cinemas all use Overpass. Parallel queries cause 429; the 6-12s timeout is too short (primary answers 200 at ~30s); the breaker then opens for 120s. location_service._overpass_elements bypasses providers._overpass_query (no mirrors, retry or breaker). The orchestrator turns the real error into "unavailable (provider error, no data returned)".
## Steps (mark [x] when done)
[x] A1 timeouts  [x] A2 rate limiter  [x] A3 unify paths  [ ] A4 stale cache  [ ] A5 narrow excepts  [ ] A6 Nominatim fallback (only if needed)
[ ] B1 defaults  [ ] B2 vague input  [ ] B3 movie rule  [ ] B4 music rule  [ ] B5 source labels  [ ] T1 transport test
[x] P1a fallback_places module (not wired into any tool)
[x] P1b Overpass budget 8s + fallback_places wired into the 3 location tools

## Log
### A1 timeouts
- Edit: Changed `overpass_timeout_s` from 6.0 to 15.0 and `overpass_budget_s` from 12.0 to 25.0 in `moodos/config.py`.
- Quick check result:
```
overpass_timeout_s=15.0, overpass_budget_s=25.0
```

### A2 rate limiter
- Edit: In `moodos/providers.py`, added module-level `_OVERPASS_LOCK` and `_OVERPASS_LAST_CALL`, wrapped `_overpass_query` with `with _OVERPASS_LOCK:`, enforced minimum gap via `OSM_MIN_INTERVAL_MS` (default 1500 ms) with throttle logging, and added HTTP 429 `Retry-After` header parsing (default 5s, capped at 10s) with sleep before next attempt/mirror.
- Quick check result:
```
2026-10-20 10:02:26,343 WARNING moodos.providers: overpass https://overpass-api.de/api/interpreter attempt 1 failed: The read operation timed out
2026-10-20 10:02:26,343 WARNING moodos.providers: overpass budget of 25.0s exhausted before https://overpass-api.de/api/interpreter (attempt 2)
2026-10-20 10:02:26,346 INFO moodos.providers: overpass rate limit throttle: sleeping 1.497s to respect min interval 1.500s
2026-10-20 10:02:51,676 WARNING moodos.providers: overpass https://overpass-api.de/api/interpreter attempt 1 failed: The read operation timed out
2026-10-20 10:02:51,676 WARNING moodos.providers: overpass budget of 25.0s exhausted before https://overpass-api.de/api/interpreter (attempt 2)
--- Call 1 start ---
--- Call 1 end (elapsed: 27.88s) ---
--- Call 2 start ---
--- Call 2 end (elapsed: 25.33s) ---
```
### A3 unify paths
- Edit: In `moodos/location_service.py`, updated `_overpass_elements` to route queries through `moodos.providers._overpass_query` instead of `_http_post_json`, unifying mirror fallbacks, retries, breaker protection, and serialization across places and cinemas.
- Quick check result:
```
=== Delhi (28.6139, 77.209) ===
find_nearby_places count: 0 (ProviderUnavailable: OpenStreetMap Overpass is unavailable (timeout, rate limit or breaker open) — no place data to return. Not falling back to a stored list.)
find_nearby_cinemas count: 0 (ProviderUnavailable: OpenStreetMap Overpass is unavailable (timeout, rate limit or breaker open) — no place data to return. Not falling back to a stored list.)
=== Mumbai (19.076, 72.8777) ===
find_nearby_places count: 0 (ProviderUnavailable: OpenStreetMap Overpass is unavailable (timeout, rate limit or breaker open) — no place data to return. Not falling back to a stored list.)
find_nearby_cinemas count: 0 (ProviderUnavailable: OpenStreetMap Overpass is unavailable (timeout, rate limit or breaker open) — no place data to return. Not falling back to a stored list.)
```
### T1 results
- Probe: `test_overpass.py` (repo root, left in place). Query `[out:json][timeout:10];node(around:2000,28.6139,77.2090)[amenity=restaurant];out center 5;` against `https://overpass-api.de/api/interpreter` only, 40s timeout, one variant at a time with 3s pause. Variants 3-7 UA: `MoodOS/0.1 (student project; https://github.com/PS-Bhargav-Gajera/moodos)`.
- Raw output:
```
=== proxy env ===
HTTP_PROXY=''
HTTPS_PROXY=''
ALL_PROXY=''
--- 1 POST data=query, project UA ---
EXC elapsed=41.03s type=ReadTimeout msg=The read operation timed out

--- 2 POST data={data: query}, project UA ---
status=200 elapsed=30.71s
body[:150]='{\n  "version": 0.6,\n  "generator": "Overpass API 0.7.62.11 87bfad18",\n  "osm3s": {\n    "timestamp_osm_base": "2026-10-20T06:28:16Z",\n    "copyright": '

--- 3 POST data={data: query}, new UA ---
status=200 elapsed=32.74s
body[:150]='{\n  "version": 0.6,\n  "generator": "Overpass API 0.7.62.11 87bfad18",\n  "osm3s": {\n    "timestamp_osm_base": "2026-10-20T06:29:20Z",\n    "copyright": '

--- 4 POST data={data: query}, new UA + Accept */* ---
status=502 elapsed=1.35s
body[:150]='# 502 Gateway Timeout\n\nThis Overpass API server is currently at capacity. All query workers are busy\nand the request queue is full.\n\n## What to do\n\nRe'

--- 5 GET params={data: query}, new UA + Accept */* ---
EXC elapsed=41.11s type=ReadTimeout msg=The read operation timed out

--- 6 POST new UA + Accept, IPv4 local_address=0.0.0.0 ---
status=502 elapsed=1.26s
body[:150]='# 502 Gateway Timeout\n\nThis Overpass API server is currently at capacity. All query workers are busy\nand the request queue is full.\n\n## What to do\n\nRe'

--- 7 POST new UA + Accept, trust_env=False ---
status=200 elapsed=35.14s
body[:150]='{\n  "version": 0.6,\n  "generator": "Overpass API 0.7.62.11 87bfad18",\n  "osm3s": {\n    "timestamp_osm_base": "2026-10-20T06:30:21Z",\n    "copyright": '
```
### P1a fallback_places
- Edit: created `moodos/fallback_places.py` exposing `fallback_places(lat, lon, category, limit=10)` — same dict shape as `location_service.search_nearby_places` (keys copied from `_build_place`), category in {restaurant, cafe, cinema, park} (park -> Overpass "walk" spec), every result's `source` set to the provider name, NOT wired into any tool. Provider choice reads only key NAMES from .env/env (names present: GROQ_API_KEY, GEMINI_API_KEY, MEM0_API_KEY, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI, DEFAULT_CITY, DEFAULT_LAT, DEFAULT_LON, TMDB_API_KEY — no GEOAPIFY_API_KEY, no FOURSQUARE_API_KEY) so it uses Nominatim `/search` (settings.nominatim_url, viewbox ±0.02°, bounded=1, 1 req/s module throttle, HEADERS UA from providers.py:19). Geoapify/Foursquare branches exist but are untested (no keys). No static lists, no hardcoded keys.
- Quick check result:
```
restaurant count: 10
first: {'id': 'nominatim:423725494', 'source_id': '423725494', 'name': 'Mysore Cafe', 'title': 'Mysore Cafe', 'category': 'restaurant', 'subtype': 'restaurant', 'kind': 'food', 'lat': 28.6082276, 'lon': 77.2016137, 'source': 'nominatim', 'address': 'Mysore Cafe, Tyagaraj Marg, Willingdon Crescent, Raisina Hill, New Delhi, Delhi, 110004, India', 'phone': None, 'website': None, 'opening_hours': None, 'opening_note': '', 'likely_closed_at': None, 'cuisine': None, 'price_level': None, 'price_tier': 'budget', 'price_is_estimate': True, 'rating': None, 'distance_km': 0.96, 'distance_label': '1.0 km', 'walk_min': 12, 'drive_min': 4, 'routing_source': 'estimate', 'estimated_cost': 250, 'duration_min': 60, 'intensity': 'low', 'crowded': False, 'outdoor': False, 'needs_clear_weather': False, 'has_venue': True, 'review_quality': 7.0, 'moods': ['happy', 'content'], 'text': 'Mysore Cafe — restaurant'}
cinema count: 2
first: {'id': 'nominatim:244650162', 'source_id': '244650162', 'name': 'Regal Cinema', 'title': 'Regal Cinema', 'category': 'cinema', 'subtype': 'cinema', 'kind': 'place', 'lat': 28.6306708, 'lon': 77.2169833, 'source': 'nominatim', 'address': 'Regal Cinema, Outer Circle, Connaught Place, New Delhi, Delhi, 110001, India', 'phone': None, 'website': None, 'opening_hours': None, 'opening_note': '', 'likely_closed_at': None, 'cuisine': None, 'price_level': None, 'price_tier': None, 'price_is_estimate': False, 'rating': None, 'distance_km': 2.02, 'distance_label': '2.0 km', 'walk_min': 24, 'drive_min': 5, 'routing_source': 'estimate', 'estimated_cost': 0, 'duration_min': 30, 'intensity': 'low', 'crowded': False, 'outdoor': False, 'needs_clear_weather': False, 'has_venue': True, 'review_quality': 7.0, 'moods': ['calm', 'warm'], 'text': 'Regal Cinema — cinema'}
```
### P1b Overpass fallback
- Edits: `moodos/config.py:50-51` — `overpass_timeout_s = 8.0`, `overpass_budget_s = 8.0` (was 15.0/25.0). `moodos/location_service.py` — import `fallback_places`, new `_FALLBACK_CATEGORY` map (cafe/restaurant/cinema/walk->park), `search_nearby_places` failure branch now calls `fallback_places` per requested category and only raises `ProviderUnavailable` when both Overpass and the fallback return nothing. `moodos/providers.py` `nearby_restaurants` failure branch — lazy `fallback_places(lat, lon, "restaurant")`, raise only if that is empty. `find_nearby_cinemas` inherits via `providers.nearby_cinemas -> search_nearby_places(categories="cinema")` (`providers.py:439`); `search_restaurants_by_mood` inherits via `nearby_restaurants` (`providers.py:753,772`). Tool names, signatures and return shapes unchanged.
- Side effect observed during the check (expected failure noise, all handled): every Overpass attempt hit the new 8s timeout, budget exhausted before mirror attempt 2, breaker OPEN after 3 failures — so all six tool calls exercised the fallback path end-to-end. The OSRM 400s are pre-existing (`osrm table failed (driving)` is logged and walk/drive estimates are used).
- Quick check result:
```
Delhi   find_nearby_places   count=24 source=nominatim                                elapsed=17.24s
Delhi   search_restaurants   count=10 source=nominatim                                elapsed=10.09s
Delhi   find_nearby_cinemas  count= 2 source=nominatim                                elapsed=12.42s
Mumbai  find_nearby_places   count=24 source=nominatim                                elapsed=5.71s
Mumbai  search_restaurants   count=10 source=nominatim                                elapsed=1.63s
Mumbai  find_nearby_cinemas  count= 3 source=nominatim                                elapsed=1.74s
```
