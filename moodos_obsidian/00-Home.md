---
tags: [moodos, index, home]
---

# MoodOS — Documentation Vault

MoodOS is a **context-aware experience orchestrator**: the user describes a mood,
a budget, and available time, and the app builds a step-by-step evening plan
(cafes, walks, a movie with a real cinema + showtime, music, books) that fits the
stated budget and duration. It runs on a zero-rupee stack.

## Top-level flow

This vault mirrors the repo at `C:\Users\BhargavGajera\Projects\MoodOS`.

```mermaid
flowchart TD
  U[User: message + budget + mood + time] --> FE[static frontend index.html + app.js]
  FE -->|POST /api/plan| API[FastAPI app.py]
  API --> LOC[POST /api/location/resolve - location.py]
  API --> OS[orchestrator.run_pipeline]

  OS --> NLU[extract_intent -> nlu.py]
  NLU -->|Groq or heuristic| SLOTS[slots: mood, budget, duration, stay_home]
  OS --> MEM[get_user_profile -> memory.py Mem0]
  OS --> RAG[retrieve_knowledge -> rag.py TF-IDF store]
  OS --> WX[get_weather -> providers.get_weather -> Open-Meteo]

  OS --> PAR[7 parallel lookups via ThreadPoolExecutor]
  PAR --> C1[find_nearby_places -> OSM Overpass]
  PAR --> C2[search_restaurants -> mood->cuisine -> OSM]
  PAR --> C3[search_music -> Spotify or iTunes]
  PAR --> C4[search_books -> Google Books]
  PAR --> C5[search_movies -> TMDB]
  PAR --> C6[find_nearby_cinemas -> OSM Overpass]
  PAR --> C7[get_weather]

  OS --> POOL[item pool + hard_filter + score_item + rerank -> ranking.py]
  OS --> PLAN[plan: _plan_with_budget LLM or _heuristic_plan]
  PLAN --> FIT[budget-fit: _assemble_plan fixed vs flexible duration]
  FIT --> TRACKS[attach real songs -> _attach_music_tracks]

  OS --> BUNDLE[{bundle: slots, mood, plan, showtimes, reviews, decisions}]
  BUNDLE --> DB[(save_event -> data/moodos.db)]
  BUNDLE --> FE2[render plan with steps + travel legs]
  FE2 --> FBI["Find restaurants (GET /api/restaurants)"]
  FE2 --> FBK["Book movie (prepare/confirm) -> actions.py"]
  FE2 --> FPL["Create playlist (seed can refresh) -> mcp.create_playlist -> Spotify"]
```

## Folder index

- **[[Architecture-Overview]]** — modules, layers, the full request path.
- **[[Request Flow]]** — what happens from `POST /api/plan` to the response bundle.
- **[[Agent Router]]** — Groq / Gemini split and heuristic fallbacks.
- **02-Tools/** — one file per MCP tool (22 tools). Entry points: [[Get Weather]], [[Search Music]], [[Create Playlist]].
- **03-Routes/** — one file per HTTP endpoint (13). Entry points: [[Route Root]], [[Route Plan]], [[Route Restaurants]], [[Route Playlist Prepare]].
- **04-Data-Sources/** — one file per provider / store. Entry points: [[Open-Meteo]], [[TMDB]], [[Spotify]].
- **05-Core-Logic/** — the scoring, planning, and budget-algorithm files. Entry points: [[Ranking and Scoring]], [[Budget Fit Duration]].
- **06-Known-Issues/** — one file per known bug. Entry point: [[Budget Fit Crash]].

## Quick map

| Concern | Where |
|---|---|
| HTTP API | `app.py` → 03-Routes (one note per endpoint) |
| Intent + mood extraction | `nlu.py`, `llm.py` → [[Intent and Mood Extraction]] |
| Planning + budget fit | `orchestrator.py` → [[Plan Assembly]], [[Budget Fit Duration]] |
| Ranking | `ranking.py` → [[Ranking and Scoring]] |
| Providers (live data) | `providers.py`, `spotify.py` → 04-Data-Sources |
| Memory | `memory.py` + `data/mem0_users.json` → [[Mem0]] |
| Knowledge RAG | `rag.py` + `data/seed_knowledge.json` → [[Knowledge RAG Store]] |
| Persistence | `db.py` → [[Local SQLite]] |
| Mock actions (booking) | `actions.py` → [[Mock cinema shows]] |

## How to read this vault

Every note carries `## Connects to` (files/tools it uses) and `## Used by`
(who calls it). Follow every Obsidian `[[...]]` link in both directions; the
Graph view shows the whole dependency web for `moodos/`.

## Verified facts note

Everything here is written from the actual source (functions cited as
`file.py:line`). Where the described behavior does **not** exist in the code,
the note says so explicitly (see [[Budget Fit Crash]] and
[[Find Restaurants button path]] for two such cases).