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
[x] R1 PLAN_PROMPT replaced (budget floor and forced-movie rule removed)
[x] R2 grouped candidates for planner prompt (ranked unchanged downstream)
[x] R3 honest leftover-time logic (rest cap 20, different-kind filler, shortfall note)

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
### R1 PLAN_PROMPT
- Edit: replaced the `PLAN_PROMPT` constant in `moodos/orchestrator.py` with the exact text supplied for step R1. Removed the old budget-floor rule ("You MUST spend at least 60% of budget_inr…") and the old forced-movie rule ("Include a movie step … if duration_hours >= 3 and stay_home is false"). Kept the five placeholders `{slots} {memory} {weather} {candidates} {shows}` and the doubled braces in the JSON schema. The only other reference (`plan_prompt = PLAN_PROMPT.format(...)` in the same file) is unchanged.
- Quick check result:
```
no-80pct OK
no-movie-forced OK
format OK 1970
```
### P1b live restart
- Diagnosis of the pasted Ahmedabad plan: the server answering /api/plan had PID 3492 started 08:53:44, while the P1b edits landed 12:22-12:24, so it was running pre-P1b code (no fallback, hence "unavailable (provider error, no data returned)" on all three location tools). Killed PID 3492, confirmed port 8000 free, relaunched uvicorn app:app (127.0.0.1:8000) with the current code. Health check:
```
health: 200 {"ok":true,"groq":true,"gemini":true,"mem0":true,"spotify":true,"spotify_user":true,"cost":"free-tier / local retrieval"}
```
### R2 grouped candidates
- Edit: in `moodos/orchestrator.py` `run_pipeline`, replaced only the `candidates=ranked[:12]` argument with `candidates=_group_candidates(ranked)`. New helper `_group_candidates` (added right after `_memory_block`) buckets `ranked` by kind, each bucket sorted by `final_score` desc: top 4 parks/walks (`kind=="place"` and `subtype in {"walk","park"}`), top 5 restaurants+cafes (`kind=="food"` or `subtype in {"cafe","food","fast_food","ice_cream","restaurant"}`), top 3 movies (`kind=="movie"` and not `watch_at_home`), top 1 music collapsed to `[{"kind":"music","title":...}]` (playlist title only, never the 24-track list), and top 2 of everything else (deduped by identity). The `ranked` list itself is untouched — later stages still use it in full.
- Quick check result (fake pool: 24 music, 24 places, 10 restaurants):
```
{'parks_walks': 0, 'restaurants_cafes': 5, 'movies': 0, 'music': 1, 'other': 0}
grouped candidates OK: >=3 restaurants
```
### R3 honest leftover-time logic
- Edits in `moodos/orchestrator.py`: (1) `_DUR_CAPS["rest"]` 45 -> 20. (2) `_best_filler` step 2 now only offers a real unused candidate whose kind DIFFERS from the previous physical stop, tried in order food -> indoor place -> park; no different-kind candidate means it returns None (giving up) instead of padding. (3) In `_assemble_plan`, when the residual shortfall is >20 min after every real candidate is used: emit a single `budget_notes` entry "Only {N} minutes of real nearby activities were found, so this plan is shorter than the {H} hours you asked for.", set `accepted_short`, break the fit loop, and skip the last-resort force-fit so nothing re-pads the plan. Residual <=20 min still becomes one small rest buffer. (4) `_diversity_why` returns the plain "A different kind of stop for a better mix." (no more "Swapped for variety"). (5) `_limit_rest_filler` clamps an over-long input rest to the rest cap and never inflates a rest into a "Remaining free time" block.
- Stale tests updated to the new contract (they asserted the old pad-to-requested-time behavior): `test_pipeline.py::test_assemble_plan_spreads_shortfall_not_all_into_one_cafe` (now expects actual_min < 300 + a budget note), and 4 buffer tests in `test_repeat_avoidance.py` (rest cap 20, honest shortfall instead of conservation).
- Quick check (3 real stops, 300-minute request, real weather so no auto-indoor step):
```
rests: [('Relaxed pacing / rest', 10)]
notes: ['Only 68 minutes of real nearby activities were found, so this plan is shorter than the 5 hours you asked for.']
total_duration_min: 232
OK: no rest > 20 min and shortfall note present
```
- Full suite: `347 passed, 1 warning in 40.69s`

### D1 duplicate places removed at the data layer
- Test first: new `tests/test_dedupe_places.py`, 4 tests, all FAILING (`_dedupe_places` missing from `moodos.fallback_places`; `_dedupe_pool` missing from `moodos.orchestrator`; `nearby_restaurants` returned the 4-row fallback list untouched).
- Edits after the failure was shown:
  - `moodos/fallback_places.py`: added `_norm_name()` (lowercase letters+digits only) and `_dedupe_places()` — two results are duplicates when their normalized names match AND they sit within 100 m, or when they share the same `source_id`; the first one is kept. `fallback_places()` now pipes its list through `_dedupe_places()` before the distance sort.
  - `moodos/providers.py::nearby_restaurants`: the P1b fallback branch now calls `_dedupe_places(fallback_places(...))` before returning.
  - `moodos/orchestrator.py`: added `_cat_group()` (food / park / cinema / indoor) and `_dedupe_pool()` — keyed on (normalized title, category group), keeps the item with the higher `final_score`, or before scoring the one with more fields filled. `run_pipeline` now runs `pool = _dedupe_pool(pool)` after the pool is built and before scoring, and `restaurants = _dedupe_pool(restaurants)` for the bundle.
- Quick check: `tests/test_dedupe_places.py` -> `4 passed in 2.02s` (the fake "Law Canteen(F2)" x2 same-id and "Pharma Canteen(F1)" x2 under 50 m rows collapse to 2 items; the same canteen arriving from both places and restaurants survives into the pool once).
- Full suite: `351 passed, 1 warning in 29.12s`.
- Note: `pytest -q` at the repo root errors on a pre-existing basename clash — the T1 transport probe `test_overpass.py` in the repo root vs `tests/test_overpass.py`. Run with `--ignore=test_overpass.py` (probe left in place per T1).

### D2 no repeated stops in a plan
- Test first: new `tests/test_no_repeated_stops.py`, both tests FAILING (`ImportError: cannot import name '_remove_duplicate_stops' from 'moodos.orchestrator'`).
- Edits after the failure was shown:
  - `PLAN_PROMPT` rule 4 now ends with "Never use the same title twice in one plan. If you run out of different candidates, leave the plan shorter."
  - `moodos/orchestrator.py`: new `_remove_duplicate_stops(plan, notes)` — walks the steps in order, keeps the first step for each `_norm_title()` key, drops any later non-travel step whose normalized title was already seen, and appends one `notes` entry per removed title: "Removed a repeated stop (<title>) so every stop in your plan is different."
  - `_assemble_plan` calls it right after `_fix_generic_place_names` and before `_clamp_plan_durations` / `_insert_travel_legs`, so travel legs are rebuilt from the surviving stops only.
  - `_best_filler` already skips titles in `used` (built from every step title) at both the music leg and the pool-filler loop — re-checked, still true, nothing changed.
- Quick check: `tests/test_no_repeated_stops.py` -> `2 passed in 1.86s`. The plan [Scoop N Munch, Law Canteen(F2), Scoop N Munch, Law Canteen(F2), music] ends with the three unique stops in order, 2 budget_notes, and exactly `len(physical)-1` travel legs connecting only the surviving physical stops.
- Full suite: `353 passed, 1 warning in 36.89s` (351 before, +2 new; none dropped).

### U1 User-Agent
- Edit: `moodos/providers.py:19` HEADERS User-Agent -> `MoodOS/0.1 (student project; https://github.com/PS-Bhargav-Gajera/moodos)`.
- Checked every Nominatim call site imports that same HEADERS dict: `providers.reverse_geocode` (:117), `providers._nominatim_nearby` (:879), `fallback_places._nominatim_search` (:203, which does `from moodos.providers import HEADERS` at :37), and `location_service._http_get_json`/`_http_post_json` (:193/:200, HEADERS imported at :40). `location_service.reverse_geocode` delegates to `providers.reverse_geocode`, so it inherits it too. No call site builds its own User-Agent.
- Quick check (httpx transport stub, no network), printing the User-Agent each path actually puts on the wire:
```
fallback_places Nominatim UA: MoodOS/0.1 (student project; https://github.com/PS-Bhargav-Gajera/moodos)
providers.reverse_geocode UA: MoodOS/0.1 (student project; https://github.com/PS-Bhargav-Gajera/moodos)
providers._nominatim_nearby UA: MoodOS/0.1 (student project; https://github.com/PS-Bhargav-Gajera/moodos)
location_service._http_get_json UA: MoodOS/0.1 (student project; https://github.com/PS-Bhargav-Gajera/moodos)
matches providers.HEADERS: OK
```

### A4 result cache + 24h stale copy
- Test first: new `tests/test_a4_cache.py`, 2 of 3 FAILING before the change (`AssertionError: {'n': 2}` — second call re-queried Overpass; and `RuntimeError` / `assert [] == ['Scoop N Munch']` — no stale copy existed to serve).
- Edits after the failures were shown:
  - `moodos/cache.py`: added `TTLCache.get_raw(key)` — same read as `get()` but ignores the entry's `expires`, so a stale copy can still be retrieved. Existing `ttl_cache` module and every other caller untouched.
  - `moodos/location_service.py` `search_nearby_places`: cache key is now `poi:{lat}:{lon}:{cat}:{radius}` (category before radius, `limit` dropped — the result is capped to `limit` before it is cached, so a cache hit already satisfies any smaller request). Final result (Overpass *or* fallback) cached `ttl_seconds=6*3600`, plus a `:stale` twin at `24*3600`. When Overpass fails *and* the fallback returns nothing, `ttl_cache.get_raw(stale_key)` is served with `log.warning("serving stale cache for %s", key)`; `ProviderUnavailable` still raised in `strict` mode with no stale copy available.
  - `moodos/providers.py` `nearby_restaurants`: same 6h + 24h stale twin. Two fixes the failing test exposed: the hit test was `if cached:` (an empty list re-queried Overpass forever) -> `if cached is not None:`; and the element parser used `el.get("lat") or (el.get("center") or {}).get("lat")`, which dropped a legitimate coordinate of `0.0` -> explicit `is not None`.
- Two pre-existing bugs found and fixed in passing, both in `providers.nearby_restaurants`: (a) the empty-list cache-hit bug above, and (b) the `0.0`-coordinate `or` bug, which silently discarded any venue sitting on the equator or prime meridian.
- Test fixture note: the first fake venue was named "Law Canteen(F2)", which `_institutional_flag` correctly rejected as a staff/campus-only canteen, so nothing was parsed and nothing was cached. Renamed the fixture to "Saganwala Restaurant".
- Quick check, per the step (real call, `28.6139, 77.2090`, `find_nearby_places` does not exist — the public API is `location_service.search_nearby_places`):
```
first call: 12.536s
second call: 0.000s
second under 0.5s: True
titles equal: True
n titles: 24
```
  Overpass timed out on attempt 1 and the budget expired before attempt 2, so the 24 titles came from the Nominatim fallback — i.e. this also confirms the *fallback* path, not only Overpass, lands in the cache.
- Test file: `tests/test_a4_cache.py` -> `3 passed in 0.15s` (second call 0.000s-0.003s on both the Overpass-mocked and restaurants-mocked paths; the third test asserts the stale copy is returned and that `strict=True` still raises when no stale copy exists).
- Full suite: `356 passed, 1 warning in 42.01s` (353 before, +3 new; none dropped).
- Note: `tests/test_a4_cache.py` lives in `tests/` next to `tests/test_overpass.py`, so it is imported as `test_a4_cache` and does not hit the root-basename clash; the `--ignore=test_overpass.py` flag is still required for the same reason as before.

### G1 fallback: institutional filter + 30-minute TTL
- Test first: new `tests/test_g1_fallback.py`, all 5 FAILING before the change (`AssertionError: ['Law Canteen(F2)', 'Pharma Canteen(F1)', 'Saganwala Restaurant']` and `assert 21599.99 <= 1800`).
- Edits after the failures were shown:
  - `moodos/providers.py` `nearby_restaurants` fallback branch: every fallback row now passes `_institutional_flag({}, p["title"])` — Nominatim rows carry no tags, so the filter runs on the name alone, exactly as the Overpass path does at :682 with real tags. Applied before `_dedupe_places`. Its cache TTL is `30 * 60` instead of `6 * 3600`; the 24h stale twin is unchanged.
  - `moodos/location_service.py` `search_nearby_places`: `ttl_seconds` is set to `6 * 3600` when Overpass responds and `30 * 60` when the fallback path is taken, then used for the single `ttl_cache.set`. The fallback rows are filtered the same way before being merged into `places`.
  - `_institutional_flag` itself is untouched — it already accepts an empty dict and matches on the name, which is why the "Law Canteen(F2)" and "Pharma Canteen(F1)" fixtures are dropped with no change to the filter.
- One D1 test needed updating as a consequence: `test_dedupe_places.py::test_nearby_restaurants_dedupes_fallback_list` used canteen names purely to exercise dedupe, which G1 now (correctly) drops. Renamed its fixtures to "Saganwala Restaurant" and "Chai Point" so it still exercises dedupe and nothing else. The other three tests in that file, which call `_dedupe_places` directly, are unaffected.
- Test file: `tests/test_g1_fallback.py` -> `5 passed in 0.08s`. The two TTL tests read the real cache entry: a fallback-sourced result leaves `left <= 1800` (and `> 1700`), an Overpass-sourced one leaves `left > 6 * 3600 - 60`.
- Full suite: `361 passed, 1 warning in 29.48s` (356 before, +5 new; none dropped).

- [x] G1 fallback institutional filter + 30m TTL for fallback-sourced results

- [x] A4 result cache (6h) + stale copy (24h) for search_nearby_places and nearby_restaurants

### G2 normalize boundary: distance_label + institutional filter + name dedupe
- Test first: new `tests/test_g2_normalize_boundary.py`, 3 of 4 FAILING before the change (`AssertionError: normalize_places must guarantee distance_label / assert None`; `assert ['Law Canteen(F2)', 'Pharma Canteen(F1)', 'Staff Cafeteria', ...] == ['Saganwala Restaurant', 'Chai Point']`; `Left contains one more item: 'Saganwala Restaurant'`).
- Root cause from the live-plan report:
  * No distance on cards: `static/app.js` `renderRestaurantCard` shows `r.distance_label` or falls back to a bare pin, and `geo.normalize_places` never set the key - so every Overpass-sourced row (the default path; no Geoapify key in `.env`) rendered as a pin.
  * Canteens on the panel despite G1: cache hits in `search_nearby_places`/`nearby_restaurants` return before any source-side filter, so rows cached pre-G1 (6h fresh / 24h stale copy) still surfaced "Law Canteen(F2)".
  * Duplicates: the plan path is deduped by `_dedupe_pool` in the orchestrator, but two OSM rows for one venue (same name within 100 m) passed straight through `normalize_places`, which the `/api/restaurants` button path uses undeduped.
- Edit after the failures were shown - `moodos/geo.py` `normalize_places` only (the single place-result contract, used by `find_nearby_places`, `search_restaurants`, `search_restaurants_by_mood`, `find_restaurants_by_cuisine` in `mcp_server.py`):
  * lazy `from moodos.providers import _institutional_flag` + `from moodos.fallback_places import _dedupe_places` inside the function body (`providers` imports `geo` at module level, so a top-level import would cycle);
  * rows whose name trips `_institutional_flag({}, name)` are dropped after name resolution - this re-runs the G1 filter at the boundary, catching stale-cache rows no source-side filter ever sees;
  * each row gains `distance_label`: a provider-supplied one is preserved verbatim, otherwise computed as `0.4 km` / `12 km` (the fallback `_fmt_km` format the panel already displays);
  * the loop result passes through the existing `_dedupe_places` (same normalized name within 100 m or same `source_id`) before the existing nearest-first sort and `limit` slice;
  * module docstring contract line updated: `distance_label` guaranteed, institutional filter, dedupe.
- Radius was already enforced here (`radius_km` filter + `mcp.search_restaurants` passes `radius_m/1000`), so "in a range or particular radius" only needed the distance display half of the ask.
- Test file: `tests/test_g2_normalize_boundary.py` -> `4 passed in 0.17s`.
- Full suite: `365 passed, 1 warning in 57.90s` (361 before, +4 new; none dropped - includes the pre-existing normalize contract tests in `tests/test_location_priority.py`, which use unique non-institutional names and assert field subsets, so the additive key and the two filters break nothing).
- Note: the dev server still runs code from before R1..G1 (restarted once, mid-session), so the live UI keeps showing the reported bugs until it is restarted.

- [x] G2 normalize boundary (distance_label + institutional filter + dedupe)
