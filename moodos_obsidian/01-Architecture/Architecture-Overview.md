---
tags: [moodos, architecture]
---

# Architecture Overview

MoodOS is a FastAPI app (`app.py`) that fronts an in-process MCP-style tool
server (`moodos/mcp_server.py`). The "MCP server" is plain classes/functions in
this repo — it is **not** a separate or remote MCP server. External services
(TMDB, OSM, iTunes, Open-Meteo, Spotify, Mem0, Groq, Gemini) are *providers*
behind the tools.

## Module map (`moodos/`)

| File | Role |
|---|---|
| `app.py` | FastAPI app: routes, request models, startup `init_db` |
| `orchestrator.py` | Pipeline: extract → lookups → rank → plan → budget-fit → bundle |
| `mcp_server.py` | `MoodOSMCPServer` — 22 tools, resources, prompt names |
| `nlu.py` | Intent/slot extraction, music-language maps, mode classifier |
| `llm.py` | `LLMRouter` — Groq (extract) and Gemini (plan) with fallbacks |
| `providers.py` | Live-data providers: Open-Meteo, OSM/Overpass/Nominatim, iTunes, Google Books, TMDB, DuckDuckGo |
| `spotify.py` | Spotify auth (app + user OAuth), track search, playlist creation |
| `ranking.py` | `hard_filter`, `score_item`, `rerank`, weights |
| `memory.py` | User memory: Mem0 Cloud + local TF-IDF fallback |
| `rag.py` | Knowledge store: TF-IDF over seed/acquired JSON docs |
| `location.py` | Confidence-ranked location resolution (user/GPS/IP) |
| `chat.py` | Short-answer chat mode (location/weather/memory/help) |
| `actions.py` | Mock booking actions (movie showtimes, confirm, food order) |
| `db.py` | SQLite persistence (users, events, feedback, knowledge_log) |
| `cache.py` | `TTLCache` persisted to `data/ttl_cache.json` |
| `jsonutil.py` | Robust LLM JSON parsing |
| `config.py` | Settings from env (keys, defaults, paths) |

## Layers

1. **Frontend** (`static/`) — `index.html` + `app.js` (vanilla JS) → see [[Frontend]].
2. **API** (`app.py`) → 03-Routes.
3. **Pipeline** (`orchestrator.py` `run_pipeline`) → 05-Core-Logic.
4. **Tools** (`mcp_server.py` `mcp.tools`) → 02-Tools.
5. **Providers / stores** → 04-Data-Sources.

## Key design points

- **Zero-rupee stack**: free keys only (`.env.example`). Fallbacks exist for
  every missing key (LLM → heuristics, TMDB → movie pool/estimates, Mem0 →
  local JSON, Spotify → iTunes).
- **Parallel live lookups**: up to 7 HTTP lookups run in a `ThreadPoolExecutor`
  (`run_pipeline`, `orchestrator.py:1293`) so one slow provider can't stall the
  whole plan (each failure degrades to `[]`).
- **Budget is duration-fit**: the plan's total minutes must equal requested
  time ± tolerance; only *flexible* steps may be stretched/shrunk. See
  [[Budget Fit Duration]].
- **Honesty over fabrication**: runtimes that aren't verified are marked
  `(est.)` + `is_estimate`; movie tone that can't be verified gets a disclaimer
  ([[Movie Metadata and Mood Fit]], [[Hard Filtering and Constraints]]).

## Connects to

- [[Request Flow]]
- [[Frontend]]
- [[Agent Router]]
- [[Mem0]] · [[Knowledge RAG Store]] · [[Local SQLite]] · [[TTL Cache]] · [[Open-Meteo]] · [[OpenStreetMap]] · [[TMDB]] · [[iTunes Search]] · [[Spotify]] · [[Google-Books]] · [[DuckDuckGo]] · [[Groq]] · [[Gemini]]

## Used by

- [[00-Home]]
- Every 02-Tools and 03-Routes note