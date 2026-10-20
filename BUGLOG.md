# BUGLOG

## PHASE 0 — DISCOVERY (facts found from code, nothing fixed yet)

### 0.1 MCP library

**There is no MCP library. Neither FastMCP nor the official SDK is installed.**

- `moodos/mcp_server.py` imports: `from moodos import actions, providers`,
  `location_service`, `mem0`, `extract_intent`, `knowledge` — **no `mcp`, no `fastmcp`.**
- `requirements.txt` has **no** `mcp` / `fastmcp` entry.
- `importlib.metadata`: `mcp` = NOT INSTALLED, `fastmcp` = NOT INSTALLED.
- No `pyproject.toml` exists.

What `MoodOSMCPServer` actually is (`moodos/mcp_server.py:17`): a plain Python
class holding three dicts/lists (`self.tools`, `self.resources`, `self.prompts`)
and a `call(name, **kwargs)` dispatcher that looks the name up in `self.tools`.
It is an **in-process tool registry**, not an MCP server:

- No stdio / SSE / streamable-HTTP transport.
- No `list_tools` / `call_tool` / `initialize` protocol handlers.
- No `/mcp` route in `app.py` (routes are `/`, `/api/*`, `/spotify/*` only).
- Therefore `npx @modelcontextprotocol/inspector` **cannot connect to anything** —
  there is no MCP endpoint to point it at. Phase 4 must use an in-process
  harness instead (call every tool, assert schema vs. reality).

Consequence for Phase 4: "check tool decorators and type hints" — there are
**no decorators**. Tools are `dict[str, Callable]` entries, mostly bare `lambda`s
with no type hints and no pydantic models. Input validation does not exist at
the tool boundary.

### 0.2 Places / restaurants / cinema / weather providers

Searched for `googleapis.com/maps`, `foursquare`, `overpass`, `nominatim`, `yelp`,
`serpapi`, `tomtom`, `geoapify`.

**Present:** `overpass` (OpenStreetMap), `nominatim` (OpenStreetMap),
`osrm` (OpenStreetMap routing), `api.open-meteo.com`, `api.tmdb.org`,
`api.spotify.com`, `ipwho.is`, `googleapis.com/books` (search_books, keyless).
**Absent:** Google Maps Places, Foursquare, Yelp, SerpAPI, TomTom, Geoapify —
none appear anywhere in the codebase, and none appear in `.env.example`.

Real call chain for the five tools:

| Tool | Declared at | Really calls | Provider | Key needed |
|---|---|---|---|---|
| `find_nearby_places` | `mcp_server.py:30` | `location_service.search_nearby_places` → `_overpass_elements` (`location_service.py:250`) | **Overpass / OSM** | no |
| `find_nearby_cinemas` | `mcp_server.py:32` | `providers.nearby_cinemas` (`providers.py`) → `location_service.search_nearby_places(categories="cinema", radius_m=15000)` | **Overpass / OSM** | no |
| `search_restaurants` | `mcp_server.py:27` | `providers.nearby_restaurants` → `_overpass_query` (`providers.py:570`) | **Overpass / OSM** | no |
| `search_restaurants_by_mood` | `mcp_server.py:28` | `providers.search_restaurants_by_mood` → `nearby_restaurants` per cuisine | **Overpass / OSM** | no |
| `get_weather` | `mcp_server.py:29` | `providers.get_weather` → `https://api.open-meteo.com/v1/forecast` | **Open-Meteo** | no |

**No tool is STATIC.** All five hit live providers. (Confirmed live, not cached-only:
the log shows real Overpass round-trips and timeouts from the running server.)

Caveat found while watching the running server — these are **live but unreliable**:

```
overpass https://overpass-api.de/api/interpreter attempt 1 failed: The read operation timed out
overpass budget of 12.0s exhausted before https://overpass.kumi.systems/api/interpreter (attempt 1)
overpass breaker OPEN after 3 consecutive failures; skipping OSM for 120.0s
```

Public Overpass is the single point of failure for **all four** place tools. When
the breaker opens, `find_nearby_places`, `find_nearby_cinemas`,
`search_restaurants`, `search_restaurants_by_mood` all return empty at once for
2 minutes. No alternative provider is configured.

### 0.3 Location entry points — the flow

Four places user location enters the system:

```
1. Browser GPS      -> PlanRequest.lat/lon + accuracy_m  (app.py:79-80, 85)
2. Typed city       -> PlanRequest.city / user_label      (app.py:82-83)
3. Client IP        -> header x-forwarded-for / client.host (app.py:148) -> ipwho.is
4. Saved profile    -> settings.default_lat/lon/city      (config.py:33-35)  [Ahmedabad]
                                  |
                                  v
resolve_location(lat, lon, user_label, ip, accuracy_m)   (location.py:124)
   builds candidates: user_label(0.98) > gps(0.82..0.92) > ip(0.45)
   winner = max(confidence) -> reverse_geocode(Nominatim) -> lat/lon/city/source
                                  |
                                  v
handle_message(msg, user_id, resolved.lat, resolved.lon, ..., location_names)  (app.py:160)
                                  |
                                  v
orchestrator run_pipeline -> mcp.call("find_nearby_*/search_restaurants/get_weather", lat, lon)
```

### 0.4 Env keys (NAMES only — no values printed)

`.env` read; every line reported as `SET len=N` or `EMPTY`. **No values logged.**

| Variable | Status | Used by |
|---|---|---|
| `GROQ_API_KEY` | SET (len 56) | `llm.py` Groq |
| `GEMINI_API_KEY` | SET (len 53) | `llm.py` Gemini |
| `MEM0_API_KEY` | SET (len 43) | `memory.py` Mem0 cloud |
| `TMDB_API_KEY` | SET (len 32) | `providers.py` all TMDB tools |
| `SPOTIFY_CLIENT_ID` | SET (len 32) | `spotify.py` |
| `SPOTIFY_CLIENT_SECRET` | SET (len 32) | `spotify.py` |
| `SPOTIFY_REDIRECT_URI` | SET (len 38) = `http://127.0.0.1:8000/spotify/callback` | `spotify.py` |
| `DEFAULT_CITY` / `DEFAULT_LAT` / `DEFAULT_LON` | SET | silent fallback (0.3) |
| `GROQ_*_MODEL`, `GEMINI_*_MODEL` | **absent from `.env`** | defaults in `config.py:25-31` — fine |
| `OVERPASS_*`, `NOMINATIM_URL`, `OSRM_URL`, `OSM_MIN_INTERVAL_MS` | **absent from `.env`** | defaults in `config.py:39-59` — fine |
| `SQLITE_PATH`, `CACHE_PATH` | **absent from `.env`** | defaults `data/moodos.db`, `data/ttl_cache.json` — fine |

**Missing keys: none.** Every provider that needs a key has one.
Place/weather providers need no key at all.

Health endpoint confirms: `groq:true gemini:true mem0:true spotify:true spotify_user:true`.

### 0.5 Server + registration

Server running: uvicorn on `http://127.0.0.1:8000`, PID confirmed listening.

Counts verified by importing the registry directly **and** over HTTP
(`GET /api/prompts`):

- **23 tools** — confirmed (both paths agree).
- **4 resources** — `user://profile`, `user://preferences`,
  `experience://cozy-evening`, `knowledge://mood/relaxation`.
- **7 prompts** — `/mood-night`, `/date-night`, `/study-session`, `/rainy-day`,
  `/weekend-plan`, `/stress-relief`, `/movie-night`.

**What "registers":** nothing registers with any MCP client or transport. The
only registrations are (a) FastAPI routes in `app.py`, (b) the in-process dicts
in `MoodOSMCPServer.__init__`, (c) `GET /api/prompts` which dumps tools+prompts
as JSON for the frontend. Resources are **never served anywhere** — grep shows
`self.resources` is written and never read by any route. It is dead state.

Doc mismatch: `moodos_obsidian/00-Home.md:56` claims **22 tools**; actual is **23**.

### 0.6 Existing tests

```
193 passed, 1 warning in 53.85s
```

**Zero failures.** The suite is hermetic (conftest blocks real HTTP and redirects
`settings.sqlite_path` + `spotify.TOKEN_PATH` to temp files per AGENTS.md), so a
green run proves nothing about live providers — it explains why the Overpass
timeouts and the Spotify issues below were never caught.

Open bugs visible in `run.err.log` (not covered by tests):

```
overpass ... attempt 1 failed: The read operation timed out
overpass breaker OPEN after 3 consecutive failures; skipping OSM for 120.0s
Gemini gemini-2.5-flash failed: 504 DEADLINE_EXCEEDED
Mem0 update <id> -> 404     (repeated)
```

---

## PHASE 2 — LOCATION ACCURACY (hybrid input: GPS + typed city)

### 2.0 Bugs found in the old location path

| # | Bug | Where | Severity |
|---|---|---|---|
| L1 | **Typed city never became coordinates.** `req.city` was only copied into `location_names` as a display label; the pipeline still searched around whatever GPS/IP/profile coords won. A user typing "Mumbai" while sitting in Ahmedabad got Ahmedabad restaurants. | `app.py:152-159` | **Critical** |
| L2 | **Silent default city.** With no GPS, no typed place and no IP, `resolve_location` returned `_default_location()` (Ahmedabad, confidence 0.1) and the plan proceeded as if that were real. | `location.py:106-121,178` | **Critical** |
| L3 | **No coordinate validation.** Lat/lng were `float()`-cast and used as-is. Out-of-range (`lat=200`) and swapped (`lat=72.5, lon=23.0`) pairs were accepted and sent straight to Overpass/Open-Meteo. | `location.py:154-163` | High |
| L4 | **Ambiguous names silently resolved to hit #1.** `geocode_text` asked Nominatim for `limit=1`, so "Springfield" became whichever Springfield Nominatim liked, with no way for the user to see or confirm the full address. | `location.py:30` | High |
| L5 | **No distance contract.** `providers.nearby_restaurants` returned rows with **no `distance_km` at all**; `location_service` computed it only when `lat and lon` were both truthy (so a venue at `0.0, 0.5` got `None`); nothing filtered by radius or sorted by distance at the tool boundary. | `providers.py:609-639`, `location_service.py:351` | High |
| L6 | **Provider failure indistinguishable from "nothing nearby".** `_overpass_elements` returned `[]` on timeout *and* on a genuinely empty area; `get_weather` returned `{"rainy": False, ...}` on failure — asserting it is **not raining** when we do not know. | `location_service.py:271-276`, `providers.py` (get_weather) | High |
| L7 | **`/api/restaurants` had its own private default.** `lat = lat or settings.default_lat` — the exact "never default silently" violation, in a second place. | `app.py:449-450` | High |

### 2.1 Design decisions

**Single shared helper.** New module `moodos/geo.py` owns the coordinate
contract. Nothing else may range-check, swap-check, or shape place rows:

- `validate_coords(lat, lon)` — the only range/swap check. Raises
  `LocationError` with a code (`invalid_coords`, `coords_out_of_range`,
  `coords_swapped`) and never silently repairs. Swap is only claimed when
  swapping actually makes both halves valid, so `lat=200, lon=400` is
  reported as out-of-range, not as a swap.
- `resolve_tool_coords(lat, lon, tool=...)` — the one entry point all five
  location tools call. There is no geocoding inside any tool.
- `normalize_places(rows, lat, lon, radius_km, limit)` — the only
  place-result shape. Guarantees `name`/`address`/`lat`/`lon`/`distance_km`/
  `source` on every row, **drops** rows with missing or impossible
  coordinates, filters by radius, sorts nearest-first.
- `LocationError` / `ProviderUnavailable` — honest failures.

**Priority order, fixed (not a confidence race).** `resolve_location` in
`moodos/location.py` now walks sources in order and stops at the first hit:

```
(a) typed place in THIS request  -> geocode_text (real Nominatim)  conf 0.98
(b) GPS lat/lng sent with request -> validate_coords                conf 0.82-0.92
(c) IP location (ipwho.is)        -> validate_coords                conf 0.45
(d) saved profile location (.env DEFAULT_*)                          conf 0.10 + notice
(e) nothing usable -> LocationError("location_required")             [428]
```

Lower-priority sources are only consulted when nothing better resolved, so an
IP lookup is no longer a wasted round-trip on every GPS request.

**Profile vs silent default — the line we drew.** `.env` *does* set
`DEFAULT_LAT/LON/CITY`, so on this machine branch (d) always fires and (e) is
unreachable in production. We kept the profile fallback (it is a legitimately
configured saved location, and removing it would break the app for users who
deny GPS) but made it **impossible to be silent**: the resolver returns
`source="profile"` plus a `notice` string, `/api/plan` copies it into
`bundle.location.resolver.notice`, the chat reply leads with it, and the
browser chip shows "saved profile location". (e) is reachable and tested by
stripping the profile — the resolver raises rather than inventing a city.

**Ambiguity = confirm, don't guess.** `geocode_text` now asks Nominatim for
`limit=5`, keeps every candidate that survives coordinate validation, and
flags `ambiguous` when a bare place name (no comma) resolves into more than
one state/country. The API answers **409** with the full candidate
`display_name`s so the UI can ask; a full address is left alone rather than
nagging.

**Honest provider failure.** `_overpass_elements` now returns `None` on
failure vs `[]` for a genuinely empty area. Tools pass `strict=True` and get a
`ProviderUnavailable` (HTTP 503) instead of an empty fake-success.
`get_weather(strict=True)` raises; the non-strict path returns `rainy: None`
(not `False`) because we do not know it is dry. `run_pipeline` catches the
raise per-lookup, records it in `bundle["provider_errors"]`, and
`tool_usage[*].source` now reads "unavailable (provider error)" instead of
claiming "Overpass/OSM (live)" for a batch that actually failed.

**Not a stored list.** The generic fill-in inside `search_restaurants_by_mood`
is the same live Overpass provider, never a cached/canned venue list, and its
failure cannot erase results already held.

### 2.2 Files changed in Phase 2

| File | Change |
|---|---|
| `moodos/geo.py` | **New.** `validate_coords`, `resolve_tool_coords`, `normalize_places`, `LocationError`, `ProviderUnavailable`. |
| `moodos/location.py` | Fixed priority order; `geocode_text` returns 5 candidates + `ambiguous`; `_profile_location()` only counts as saved when `DEFAULT_LAT` *and* `DEFAULT_LON` are actually in the environment (not just compiled-in code defaults); raises instead of `_default_location()`. |
| `moodos/location_service.py` | `_overpass_elements` → `None` on failure; `search_nearby_places(..., strict=False)`. |
| `moodos/providers.py` | `nearby_restaurants` / `search_restaurants_by_mood` / `nearby_cinemas` / `get_weather` gain `strict`; `get_weather` failure reports `rainy: None`. |
| `moodos/mcp_server.py` | The five location tools became real methods on `MoodOSMCPServer` (were bare lambdas) — each calls `resolve_tool_coords` then `normalize_places`. |
| `moodos/orchestrator.py` | Weather fetch wrapped; `provider_errors` / `failed_tools` recorded; `_live_source()` makes `tool_usage` provenance admit failure; `used_default_location` accepts `"profile"`. |
| `moodos/chat.py` | `live_facts` treats `source="profile"` as a non-live location and surfaces the notice. |
| `app.py` | `req.city` now reaches the resolver as typed input; exception handlers → `LocationError` 400/428, `ProviderUnavailable` 503; ambiguous → 409; `/api/restaurants` uses the shared resolver (silent default removed). |
| `static/app.js` | `sourceName` knows "profile"; resolve/plan/restaurant errors surface the real message; ambiguity shows candidate addresses. |

### 2.3 Live verification (real Nominatim / Overpass / Open-Meteo)

`python scripts/smoke_location_live.py`:

```
=== 1. geocode two far-apart typed cities (real Nominatim) ===
  Mumbai     19.054999, 72.8692035  |  Mumbai, Mumbai Suburban District, Maharashtra, 400051, India
  Delhi      28.6328027, 77.2197713  |  Delhi, India
  distance Mumbai<->Delhi      1148.1 km

=== 2. resolve_location priority ===
  typed Mumbai + GPS Ahd       user 19.054999, 72.8692035 (Mumbai)
  GPS only                     gps 23.0225, 72.5714 (Ahmedabad)
  ungeocodable typed           geocode_failed: Could not geocode "zzzz nowhere"...
  swapped coords               coords_swapped

=== 3. find_nearby_places: results change + stay in radius ===
  Mumbai                       6 cafes, nearest=mahatma nagar @2.84km, farthest=3.88km
  Delhi                        6 cafes, nearest=Madras Coffee House @2.12km, farthest=3.89km

=== 4. get_weather (Open-Meteo) ===
  Mumbai                       37.0C  clear  (open-meteo)
  Delhi                        31.6C  rain   (open-meteo)

=== 5. search_restaurants: same shape contract ===
  Mumbai restaurants           5 rows
```

Both cities resolve to **different** coordinates (1148 km apart) and every
returned row is inside the 4 km radius, nearest-first, with the full
name/address/lat/lon/distance_km/source contract. A real Overpass 504 seen
during the run came back as `ProviderUnavailable` ("OpenStreetMap Overpass is
unavailable (timeout, rate limit or breaker open)… Not falling back to a
stored list") rather than an empty 200 — which is exactly the required
behaviour.

### 2.4 Tests

- New: `tests/test_location_priority.py` — **44 tests** covering coordinate
  validation (range/swap/non-numeric), the place-result contract, all five
  priority branches, ambiguity, the two-far-apart-cities proof, all five tools
  sharing one validator, all five tools reporting a dead provider, and the
  HTTP surface (400 / 409 / 428 / 503 / profile notice).
- Changed: `test_permission_denied_or_no_fix_falls_to_default` →
  `test_no_fix_falls_back_to_profile_and_says_so` +
  `test_no_fix_at_all_raises_instead_of_inventing_a_city` (the old assertion
  `source in {"default","ip"}` was the silent-default bug codified as a test).

```
237 passed, 1 warning in 21.17s
```

---

## PHASE 3 — SPOTIFY, LAYER BY LAYER

Live audit script: `python scripts/smoke_spotify_live.py` (deliberately not part
of pytest — it talks to real Spotify and reads the real
`data/spotify_tokens.json`). Every layer prints the exact HTTP status and the
body Spotify returned, so a failure is attributable to one layer rather than
"Spotify is broken". All seven layers passed.

### 3.1 What each layer showed (live, against real Spotify)

| Layer | Endpoint / call | Result |
|---|---|---|
| 1. Configuration | `.env` → `config.settings` | `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` both set; `redirect_uri = http://127.0.0.1:8000/spotify/callback` |
| 2. Client-credentials | `POST https://accounts.spotify.com/api/token` | **200** — `{"access_token": "BQ…", "token_type": "Bearer", "expires_in": 3600}`. `app_access_token()` caches it and skips the second call. |
| 3. Search | `GET https://api.spotify.com/v1/search?type=track` | **200** for `market=IN` and `market=US`, 5 items each. Raw `limit=20` → **400** — confirms the `min(limit, 10)` clamp in `search_tracks` is load-bearing, not defensive. |
| 3b. Search (module) | `search_tracks("calm evening", limit=50)` | 10 rows (clamped). Full contract present on row 0: `id=spotify:38Qh…`, `uri`, `name="Calm Evening"`, `artist="Derrol"`, `title`, `kind=music`, `source=spotify`, `duration_min=2.0`, `duration_sec=122`, `intensity=low`, `preview_url=None`, `url`. |
| 4. OAuth authorize | `authorize_url()` | `accounts.spotify.com/authorize`, `response_type=code`, `redirect_uri` matches settings, 5 scopes requested (both `playlist-modify-*` + `user-read-private`/`user-read-email`/`user-read-private`), 16-char random `state`. Stale and empty `state` both rejected with `invalid_state`. |
| 5. Stored grant | `data/spotify_tokens.json` | Connected; `granted_scopes()` = all 5; `scope_gap() == []`; `can_create_playlists() is True`. |
| 6. Refresh | `POST /api/token grant_type=refresh_token` | **200** — new access token, and the refreshed grant **still carries `playlist-modify-public`** (scope is preserved across refresh, as Spotify documents). `_user_access_token()` returns the new token. |
| 7. Create | `create_playlist(..., confirm=False)` | `aborted` without touching Spotify. A real create was **not** run — the script never writes to the user's account. |

### 3.2 Bugs found and fixed in the music leg

All three are the same class as the Phase 2 location bugs: a provider failure
was indistinguishable from a legitimate empty result.

| # | Bug | Where | Fix |
|---|---|---|---|
| **M1** | **A failed search was cached for 20 minutes.** `search_music` called `ttl_cache.set(key, tracks, 20*60)` unconditionally. `search_tracks` returns `[]` on *any* failure (401/403/429/5xx/timeout) as well as on a genuine no-match, so one transient Spotify outage was frozen into the TTL cache and every subsequent request for that mood returned silence. | `providers.py:891` | Only cache a non-empty result. An empty list is ambiguous, so it is never written to the cache. |
| **M2** | **Empty playlist could be prepared and then created on the user's real account.** `mcp_server.create_playlist(confirm=False)` returned `prepared` with `tracks: []` when Spotify was down; confirming that then called `spotify.create_playlist(name, [], confirm=True)`, which happily POSTed `/v1/users/{id}/playlists` and returned `executed: True` — a real, empty playlist on the user's Spotify. | `mcp_server.py:210`, `spotify.py:435` | Two guards: `mcp_server.create_playlist` refuses to prepare when `tracks` is empty and says why; `spotify.create_playlist` refuses to create when `uris` is empty (`create_failed`, "There were no tracks to add, so no playlist was created."). Neither guard reaches Spotify. |
| **M3** | **Silent truncation at the add-tracks step.** `uris[:50]` dropped the tail with no signal, and Spotify's actual cap is 100 per call — so up to 50 tracks were being discarded unnecessarily. The success payload also reported nothing about how many tracks landed. | `spotify.py:513-518` | Cap raised to Spotify's real limit of 100; the result now carries `tracks_added` / `tracks_requested` so a short playlist is visible rather than implied. |

Not changed, logged for the record: the playlist `description` is still the
hardcoded string `"MoodOS calming evening playlist"` regardless of the mood or
query (`spotify.py:503`) — cosmetic, no data risk.

### 3.3 Tests

New: `tests/test_spotify_layers.py` — **30 tests** covering all seven layers:

```
267 passed, 1 warning in 18.22s
```

(237 from Phase 2 + 30 new.) One pre-existing test needed updating:
`test_errors.py::test_playlist_create_me_failure_logs_its_own_detail` used an
empty URI list to reach the `GET /v1/me` failure path. The new empty-guard
correctly intercepts before that call, so the test now passes a real URI to
exercise the path it actually means to cover.

---

