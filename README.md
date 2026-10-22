# MoodOS

**Mood-aware experience orchestration** — *mood + context + constraints → a coherent real-world experience.*

MoodOS is a FastAPI application that takes how you feel and what your day looks like (mood, budget, time, company, location, weather) and turns it into a concrete, timed plan: places to visit, movies to watch, music to play, food to eat — grounded in live data, not just LLM guesses.

> **The LLM is not the database.** Groq and Gemini only *reason* and *call tools*. Facts come from Mem0, local RAG, and live APIs (Open-Meteo, OpenStreetMap, TMDB, Spotify, Google Books, DuckDuckGo).

---

## Table of Contents

- [Key Features](#key-features)
- [How It Works](#how-it-works)
- [Groq vs Gemini](#groq-vs-gemini)
- [Zero-Rupee Stack](#zero-rupee-stack)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [Project Structure](#project-structure)
- [Module Map](#module-map)
- [MCP (Model Context Protocol)](#mcp-model-context-protocol)
- [Live Terminal](#live-terminal)
- [Testing](#testing)
- [Architecture Docs](#architecture-docs)
- [What This Is Not](#what-this-is-not)

---

## Key Features

| Feature | Description |
|---|---|
| **Experience Plans** | Free-text message ("stressful day, ₹1200, 5 hours, solo") → a timed timeline with travel legs, budget breakdown, and a grounded explanation. |
| **Chat Mode** | Direct answers (weather, "where am I?") without a full plan. |
| **Location Fusion** | Typed place > browser GPS > public IP > `.env` profile, with ambiguity resolution (409 candidates). |
| **Live Weather** | Open-Meteo current/forecast/hourly data + activity-suitability scoring (Weather MCP). |
| **Places & Routes** | OpenStreetMap Overpass POIs with mirrors, circuit breaker, rate-limiting, Nominatim fallback, TTL cache; OSRM routes. |
| **Movies** | TMDB now-playing + estimated showtimes; streaming suggestions for stay-home plans; confirm-gated mock booking. |
| **Music** | Live Spotify search; user OAuth to create real playlists (explicit prepare → confirm). |
| **Persistent Memory** | Mem0-compatible memory (Cloud if key set, else local JSON + TF-IDF): preferences, episodic facts, patterns, feedback. Guarded writes with dedupe. |
| **RAG** | Local TF-IDF retrieval over seed + acquired knowledge docs. |
| **Mood Journal** | Deterministic (LLM-free) mood time-series: entries per plan, trends, SVG chart, calendar heatmap, reactions that feed learning. |
| **Crisis Safety** | Regex short-circuit (no LLM, no logging of message text) with warm support reply + India Tele-MANAS helplines (14416 / 112). |
| **Repeat Avoidance** | Recently-shown items are tracked and deprioritized so plans don't repeat. |
| **Group Budget** | Party-size aware budget math and hard filters in ranking. |
| **Live Terminal** | In-browser SSE panel streaming every Client ↔ Orchestrator ↔ MCP tool call/result in real time. |
| **Provider Resilience** | Groq↔Gemini cross-fallback → pure heuristics; the app fully runs with **zero API keys**. |

---

## How It Works

```
User message
   │
   ├─ Crisis check (deterministic regex, short-circuits if needed)
   ├─ Location resolve (typed → GPS → IP → profile)
   ├─ NLU extract (Groq fast agent → heuristic fallback)
   │     intent · mood · budget · time · party · location slots
   │
   ├─ Candidate gathering (live providers)
   │     places (OSM) · weather (Open-Meteo) · movies (TMDB)
   │     music (Spotify) · books · web · RAG knowledge
   │
   ├─ Rank & dedupe (weighted scoring, group budget, repeat avoidance)
   │
   ├─ Plan generation (Gemini → Groq → heuristics)
   │     timeline assembly with travel legs + explanations
   │
   ├─ Side effects
   │     journal entry · event save (SQLite) · memory write (guarded)
   │     optional actions: booking / playlist (explicit confirm)
   │
   └─ Response
         chat reply  OR  full plan bundle (meta-grid + timeline + cards)
```

---

## Groq vs Gemini

| Agent | Provider | Model (free tier) | Job |
|---|---|---|---|
| Extract / Mood / slots | **Groq** (first) | `openai/gpt-oss-20b` | Fast JSON: intent, mood, budget, time, intensity |
| Plan / explain | **Gemini** (first) | `gemini-2.5-flash` (fallbacks if renamed) | Experience sequence + grounded explanation |
| Fallback | The other provider, then local rules | — | App still runs with **no keys** using heuristics + seed knowledge |

Groq is used for speed (many small structured calls). Gemini is used for the longer planning pass. Neither is treated as ground truth for showtimes, weather, or prices.

---

## Zero-Rupee Stack

| Piece | Choice | Cost |
|---|---|---|
| App / MCP server | FastAPI (local) | Free |
| User memory (Mem0-style) | Local JSON + TF-IDF | Free |
| RAG | Local TF-IDF over seed + acquired docs | Free |
| Live weather | Open-Meteo | Free, no key |
| Places | OpenStreetMap Nominatim / Overpass | Free, no key |
| Music | Spotify (live search; no fallback) | Free key |
| Books | Google Books | Free, no key |
| Movies (optional) | TMDB | Free key |
| Movies (default) | TMDB now-playing + estimated showtimes | Free |
| Web fallback | DuckDuckGo (`ddgs`) | Free |
| Cache | File TTL (Redis-shaped) | Free |
| App DB | SQLite | Free |
| Booking / food order | Mock providers + explicit confirm | Free |

---

## Quick Start

```powershell
cd MoodOS
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app:app --reload --port 8000
```

Open **http://127.0.0.1:8000**

> The app works with an empty `.env` (heuristic pipeline + seed knowledge). Add free keys below to enable the LLM agents, Spotify playlists, and TMDB movies.

Optional live-terminal monitor (separate shell):

```powershell
python scripts/live_terminal.py --url http://127.0.0.1:8000
```

---

## Environment Variables

Copy `.env.example` → `.env`. **Never commit `.env`** — it is gitignored.

### Keys (free tier, no credit card)

| Variable | Purpose | Get it at |
|---|---|---|
| `GROQ_API_KEY` | Fast structured extraction agent | https://console.groq.com |
| `GEMINI_API_KEY` | Planning / explanation agent | https://aistudio.google.com/apikey |
| `MEM0_API_KEY` | Mem0 Cloud (optional; local JSON memory if empty) | https://app.mem0.ai |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Spotify app for playlist creation | https://developer.spotify.com/dashboard |
| `SPOTIFY_REDIRECT_URI` | Must be `http://127.0.0.1:8000/spotify/callback` | — |
| `TMDB_API_KEY` | Movies (optional) | https://www.themoviedb.org/settings/api |

### Defaults

| Variable | Default |
|---|---|
| `DEFAULT_CITY` | Ahmedabad |
| `DEFAULT_LAT` / `DEFAULT_LON` | 23.0225 / 72.5714 |

### Optional Overrides (defaults shown)

- **LLM models:** `GROQ_FAST_MODEL` (`openai/gpt-oss-20b`), `GROQ_REASON_MODEL` (`openai/gpt-oss-120b`), `GEMINI_PLAN_MODEL` (`gemini-2.5-flash`), `GEMINI_FALLBACK_MODELS` (comma list)
- **OSM:** `OVERPASS_URL`, `OVERPASS_MIRRORS`, `OVERPASS_TIMEOUT_S` (8.0), `OVERPASS_BUDGET_S` (8.0), `OVERPASS_TRIP_AFTER` (3), `OVERPASS_COOLDOWN_S` (120), `NOMINATIM_URL`, `OSRM_URL`, `OSM_MIN_INTERVAL_MS` (900)
- **Storage:** `SQLITE_PATH` (`data/moodos.db`), `CACHE_PATH` (`data/ttl_cache.json`)

---

## API Reference

### Page / Health

| Method | Path | Notes |
|---|---|---|
| GET | `/` | Serves the web UI |
| GET | `/api/health` | Provider readiness (groq / gemini / mem0 / spotify) |

### Core

| Method | Path | Notes |
|---|---|---|
| POST | `/api/plan` | Main endpoint: crisis check → location resolve → pipeline. 409 on ambiguous location, 428/400 on location errors |
| POST | `/api/location/resolve` | Location fusion only |
| POST | `/api/feedback` | like / dislike / note → memory + SQLite + plan-outcome learning |

### Memory (Mem0-style)

| Method | Path |
|---|---|
| GET | `/api/mem0` |
| POST | `/api/mem0/remove` |
| PUT | `/api/mem0/{memory_id}` |
| DELETE | `/api/mem0/{memory_id}` |
| DELETE | `/api/memory/all` |

### Actions (confirm-gated)

| Method | Path |
|---|---|
| POST | `/api/booking/prepare` |
| POST | `/api/booking/confirm` |
| POST | `/api/playlist/prepare` |
| POST | `/api/playlist/confirm` |
| GET | `/api/restaurants` |

### Spotify OAuth

| Method | Path |
|---|---|
| GET | `/spotify/login` |
| GET | `/spotify/callback` |

### MCP Discovery (in-process registry)

| Method | Path |
|---|---|
| GET | `/api/prompts` |
| GET | `/mcp/tools` |
| GET | `/mcp/resources` |
| GET | `/mcp/prompts` |
| GET | `/mcp/tools/{name}` |

### Weather MCP

| Method | Path |
|---|---|
| POST | `/mcp/weather` | JSON-RPC 2.0 |
| GET | `/mcp/weather/tools` |
| POST | `/mcp/weather/call` |
| GET | `/api/weather/current` |
| GET | `/api/weather/forecast` |
| GET | `/api/weather/hourly` |
| GET | `/api/weather/activity` |

### Live Terminal

| Method | Path |
|---|---|
| GET | `/api/live-terminal/stream` | SSE |
| GET | `/api/live-terminal/history` |

### Journal

| Method | Path |
|---|---|
| GET | `/api/journal` |
| GET | `/api/journal/trends` |
| GET | `/api/journal/strip` |
| POST | `/api/journal/react` |
| DELETE | `/api/journal/{entry_id}` |
| DELETE | `/api/journal` |

**Error handling:** a global 500 handler returns a generic message + `error_id` (no leaked internals). `LocationError` → 428/400; `ProviderUnavailable` → 503 with an honest explanation.

---

## Project Structure

```
MoodOS/
├── app.py                     # FastAPI entrypoint — all HTTP routes
├── requirements.txt
├── .env.example               # Template for environment variables (copy to .env)
├── README.md / PROGRESS.md / PLAN.md / BUGS.md / AGENTS.md
│
├── moodos/                    # All backend logic
│   ├── config.py              # Pydantic settings (.env loading, defaults, paths)
│   ├── db.py                  # SQLite layer (events, feedback, journal, users)
│   ├── llm.py                 # Dual-provider LLM router (Groq + Gemini, fallbacks)
│   ├── providers.py           # Live API layer: weather, TMDB, books, web, OSM, Spotify
│   ├── nlu.py                 # Intent / mood / slot extraction (LLM + heuristics)
│   ├── chat.py                # Direct-answer chat mode (no plan)
│   ├── orchestrator.py        # The brain — pipeline: extract → gather → rank → plan → save
│   ├── actions.py             # Confirm-gated movie booking / mock providers
│   ├── memory.py              # Mem0-compatible memory (Cloud or local JSON + TF-IDF)
│   ├── memory_writer.py       # Guarded memory writes (dedupe, transient blocking)
│   ├── journal.py             # Deterministic mood journal (SQLite time-series)
│   ├── crisis.py              # Crisis phrase short-circuit + helplines (no LLM)
│   ├── ranking.py             # Candidate scoring, filters, group budget
│   ├── mood_map.py            # Mood normalization (free text → -1..+1 valence)
│   ├── location.py            # Location fusion (typed > GPS > IP > profile)
│   ├── location_service.py    # OSM abstraction: nearby, geocode, routes
│   ├── geo.py                 # Geometry/contract helpers, LocationError
│   ├── weather_mcp.py         # Open-Meteo Weather MCP (JSON-RPC 2.0 server + client)
│   ├── mcp_server.py          # In-process MCP tool registry (23 tools, resources, prompts)
│   ├── terminal_stream.py     # Real-time ANSI terminal bus (SSE + stdout)
│   ├── spotify.py             # Spotify search + user OAuth playlist creation
│   ├── rag.py                 # Local TF-IDF knowledge store
│   ├── cache.py               # File-backed TTL cache
│   ├── fallback_places.py     # Nominatim fallback POI lookup
│   └── jsonutil.py            # Tolerant LLM JSON extraction
│
├── static/                    # Frontend (vanilla JS, no build step)
│   ├── index.html             # Single-page UI
│   ├── app.js                 # ~1,400 lines: plan/chat render, journal, terminal, modals
│   └── styles.css
│
├── data/                      # Runtime data (gitignored except seed)
│   ├── seed_knowledge.json    # Seed RAG documents
│   ├── moodos.db              # SQLite (events, feedback, journal, users)
│   ├── mem0_users.json        # Local memory store
│   ├── ttl_cache.json         # TTL cache
│   └── spotify_tokens.json    # Spotify OAuth tokens
│
├── tests/                     # Pytest suite (~365 tests, hermetic/network-free)
│   ├── conftest.py            # Network guard + storage redirection fixtures
│   ├── test_pipeline.py / test_routes.py / test_chat.py / test_crisis.py
│   ├── test_journal.py / test_preferences.py / test_mcp_schema.py
│   ├── test_weather_mcp.py / test_spotify_layers.py / test_overpass.py
│   └── ... (dedupe, repeat-avoidance, group budget, fallback, errors, QA edges)
│
├── scripts/                   # Dev / smoke / audit tooling
│   ├── live_terminal.py       # Standalone SSE terminal monitor
│   ├── smoke_plan.py / smoke_chat.py / smoke_action.py / smoke_spotify_live.py
│   ├── probe_overpass.py / check_keys.py
│   └── dump_mcp_schema.py / audit_mcp_calls.py / inspect_weather_mcp_traffic.py
│
├── docs/architecture/         # System architecture diagrams + worked example
└── frontend template/         # Static HTML design mockups
```

---

## Module Map

One-line summary of every module in `moodos/`:

| Module | Purpose |
|---|---|
| `config.py` | Pydantic `Settings` — loads `.env`, model names, default city, OSM endpoints, storage paths; creates `data/`. |
| `db.py` | Thread-safe SQLite layer — users, recommendation_events, feedback, mood_entries, shown_items. |
| `llm.py` | `LLMRouter` — Groq fast + Gemini plan, 25s hard timeout, cross-provider fallback then heuristics. |
| `providers.py` | The big live-API layer (~1,500 lines): Open-Meteo, TMDB, Google Books, DuckDuckGo, Spotify, Overpass/Nominatim/OSRM with mirrors, rate limiting, circuit breaker, TTL + stale caching. |
| `nlu.py` | Intent/slot extraction: 8s-budgeted LLM extract with instant heuristic fallback; mood/budget/time/party detection; haversine. |
| `chat.py` | Direct-answer chat: gathers live facts (place, weather, memories) and prompts the LLM for a 1–3 sentence grounded reply. |
| `orchestrator.py` | The brain (~2,700 lines): extract → gather candidates → rank/dedupe → LLM plan → assemble timeline with travel legs → explain → journal + event save. |
| `actions.py` | Side-effect actions with explicit confirm: movie showtimes + mock booking prepare/confirm. |
| `memory.py` | Mem0-compatible memory: Cloud when `MEM0_API_KEY` set, else local JSON + TF-IDF retrieval. |
| `memory_writer.py` | Guarded memory write path: transient-word blocking, search-before-write dedupe, confidence reinforcement. |
| `journal.py` | Deterministic, LLM-free mood journal: entries, trends, summary strip, insight rules, reactions. |
| `crisis.py` | Deterministic crisis phrase short-circuit — regex, no LLM, no logging of message text. |
| `ranking.py` | Weighted candidate scoring (mood, preference, context, reviews, novelty, distance), hard filters, group budget. |
| `mood_map.py` | Dependency-free mood normalization: lexicon → −1..+1 valence + intensity. |
| `location.py` | Location resolver: typed place > GPS > IP > profile; reverse-geocode; `LocationError` when nothing usable. |
| `location_service.py` | Single OSM abstraction: nearby POIs (6h cache + 24h stale twin), place details, routes (OSRM or estimate). |
| `geo.py` | Shared geometry/contract: `validate_coords`, `normalize_places`, `LocationError`, `ProviderUnavailable`. |
| `weather_mcp.py` | Open-Meteo Weather MCP: JSON-RPC 2.0 handler, 5 tools, WMO knowledge base, activity scoring. |
| `mcp_server.py` | In-process tool registry: 23 tools, 4 resources, 7 prompt slugs; `inspect.signature` schema + `call()` dispatcher. |
| `terminal_stream.py` | Real-time ANSI terminal bus: logs tool calls/results to stdout + SSE for the browser panel. |
| `spotify.py` | Spotify search via app credentials; playlist creation via user OAuth (authorize, code exchange, scope-gap detection). |
| `rag.py` | `KnowledgeStore` — local TF-IDF RAG over seed + acquired knowledge docs. |
| `cache.py` | `TTLCache` — file-backed JSON TTL cache (`get`, `get_raw` for stale reads, `set`). |
| `fallback_places.py` | Nominatim `/search` fallback POIs (cafe/restaurant/cinema/park) when Overpass fails. |
| `jsonutil.py` | Tolerant JSON extraction: strips markdown fences, regex-extracts `{...}`, returns `{}` on failure. |

---

## MCP (Model Context Protocol)

> Note: there is **no MCP SDK** in this project — these are purpose-built in-process registries shaped like MCP.

### 1. Tool Registry (`moodos/mcp_server.py`)

`MoodOSMCPServer` holds **23 tools** (mood analysis, movie/music/book/restaurant search, weather, nearby places, knowledge retrieval, booking, playlist creation, TMDB details…), **4 resources** (`user://profile`, `user://preferences`, `experience://cozy-evening`, `knowledge://mood/relaxation`), and **7 prompt slugs** (`/mood-night`, `/date-night`, `/study-session`, `/rainy-day`, `/weekend-plan`, `/stress-relief`, `/movie-night`).

- Schemas derived via `inspect.signature` (bound methods, never lambdas).
- `call(name, **kwargs)` is the only dispatch path.
- Read-only discovery at `/mcp/tools`, `/mcp/resources`, `/mcp/prompts`, `/mcp/tools/{name}`.

### 2. Weather MCP (`moodos/weather_mcp.py`)

`OpenMeteoWeatherMCPServer` speaks **JSON-RPC 2.0** (`initialize`, `tools/list`, `tools/call`; protocolVersion `2024-11-05`) with **5 tools**:

| Tool | Description |
|---|---|
| `get_current_weather` | Current conditions for lat/lon |
| `get_weather_forecast` | Multi-day forecast |
| `get_hourly_forecast` | Hourly breakdown |
| `get_weather_by_city` | Forecast by city name |
| `evaluate_weather_for_activity` | Suitability score for outdoor/indoor activities |

Exposed at `/mcp/weather` (JSON-RPC), `/mcp/weather/tools`, `/mcp/weather/call`, plus REST wrappers (`/api/weather/*`).

### 3. MCP Traffic Visibility

Every tool call/result (main registry + weather MCP) is logged through `terminal_bus` and streamed live to the UI's **Live MCP Communication** panel and to `scripts/live_terminal.py`. Audit tooling: `scripts/audit_mcp_calls.py`, `scripts/dump_mcp_schema.py`, `scripts/inspect_weather_mcp_traffic.py`.

---

## Live Terminal

The UI's **📟 Live Terminal** panel (and `scripts/live_terminal.py`) streams every internal hop in real time over SSE:

```
Client ──▶ Orchestrator ──▶ MCP tool ──▶ Provider (Open-Meteo / OSM / TMDB / …)
```

Useful for debugging which providers were consulted, what the LLM returned, and where time was spent — without tailing server logs.

---

## Testing

**Framework:** pytest (pinned in `requirements.txt`).

```powershell
python -m pytest -q --ignore=test_overpass.py
```

> `--ignore=test_overpass.py` skips a root-level probe file that would clash by basename with `tests/test_overpass.py`.

**Hermetic guarantees** (enforced by `tests/conftest.py`):

1. **Network guard** — real outbound HTTP raises `RuntimeError("network disabled in tests")`; in-process transports (TestClient ASGI, MockTransport) pass through.
2. **Storage redirection** — `settings.sqlite_path`, `settings.cache_path`, and `spotify.TOKEN_PATH` point at a temp dir; tests never touch `data/*.db`, the real TTL cache, or a live Spotify session.
3. **Autouse fixtures** — Overpass circuit breaker reset per test; offline-OSM patches; TTL cache snapshotted and cleared per test.

**~365 tests** across 27 modules cover: pipeline/plan assembly, routes, chat, crisis, journal, preferences, MCP schemas & call signatures, weather MCP, Spotify layers, location priority/service, Overpass, caching, dedupe, repeat avoidance, group budget, fallback (G1), normalize boundary (G2), errors, and QA edge cases.

---

## Architecture Docs

- [System Architecture](docs/architecture/diagram-a-system-architecture.md)
- [Worked Example](docs/architecture/diagram-b-worked-example.md)
- [Architecture Overview](docs/architecture/README.md)

---

## What This Is Not

- Not `User → LLM → list of items`
- Not paid BookMyShow scraping
- Not "Mem0 eliminates hallucinations"
- Not "RAG trains the model"
- Not production — it is a learning project, hardened iteratively (see `PROGRESS.md`)

---

## License

No license file is included yet. All rights reserved by the author unless a license is added.
