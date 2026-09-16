---
tags: [moodos, architecture, request-flow]
---

# Request Flow

End-to-end path of a "build me an evening" (or short-chat) request.

## 1. Frontend prepares the request

`static/app.js` → `run()` (`app.js:551-597`) waits for GPS/watch, follows the
form (`index.html`, `#msg` textarea, `#loc` city, `#prompt` workflow select),
resolves location first (**[[Route Location Resolve]]**), then:

```
POST /api/plan
{message, prompt, lat, lon, user_label, ip}
```
90 s `AbortController` timeout (`app.js:571`); any error → generic "Oops"
page (`app.js:583-593`) — this is what hides backend crashes, see
[[Budget Fit Crash]].

## 2. HTTP API (`app.py:85` [[Route Plan]])

- Resolves IP/location → `resolve_location(...)` ([[Location Resolution]]).
- Calls `orchestrator.handle_message(message, user_id, lat, lon, prompt)`.
- Attaches the resolver audit block (`source`, `confidence`, `gps_live`...).

## 3. Pipeline (`orchestrator.py`)

`handle_message` (`orchestrator.py:246`) classifies **plan vs chat** via
`classify_turn` (`nlu.py:145`); chat short-answers go through [[Direct Chat]].
Plans go to `run_pipeline` (`orchestrator.py:1185`):

1. `ensure_user` + `reverse_geocode` (`orchestrator.py:1192-1196`)
2. `extract_intent` → slots ([[Intent and Mood Extraction]])
3. mood/prefs rebuilt from slots (no 2nd LLM call) (`:1206-1220`)
4. `get_user_profile` memories ([[Mem0]]) + decision log
5. `retrieve_knowledge` RAG ([[Knowledge RAG Store]]); if confidence < 0.12 →
   web snippets + ingest (adaptive fallback, `:1313-1326`)
6. `get_weather` ([[Open-Meteo]])
7. music language: explicit slot, else inferred from state/city
   ([[Music Language Resolution]], `:1246-1252`)
8. **7 parallel lookups** in `ThreadPoolExecutor`
   (`:1293`, see [[Architecture-Overview]]): places, music, books, movies,
   restaurants, cinemas, weather.
9. item pool + `hard_filter` + `score_item` + repeat-penalty + `rerank`
   (`:1357-1367`, [[Ranking and Scoring]], [[Hard Filtering and Constraints]])
10. plan: `_plan_with_budget` (Gemini/Groq, with budget/weather context) or
    `_heuristic_plan` fallback (`:1376-1378`, [[Plan Assembly]])
11. `_assemble_plan` budget-fit ([[Budget Fit Duration]])
12. `_attach_music_tracks` attaches the real searched songs
    (`orchestrator.py:805`, `:1380`)
13. movie note / remember suggestions / review classification
    (`:1381-1389`)
14. bundle built with `tool_usage`, `decisions`, `retrieval_path`, `agents`,
    `action` (`:1391-1443`)
15. `save_event` → SQLite (`:1444`), `event_id` added.

## 4. Response bundle

The bundle is what `app.js` `render(data)` consumes
(`app.js:360-546`): slots/mood/prefs meta, weather, ranked list, the `plan`
step list (steps + travel legs + music `tracks`), showtimes, restaurants,
streaming_movies, reviews. See [[Frontend]].

## Connects to

- [[Route Plan]] · [[Route Location Resolve]] · [[Route Health]]
- [[Direct Chat]]
- [[Budget Fit Duration]] · [[Plan Assembly]] · [[Ranking and Scoring]]

## Used by

- [[Architecture-Overview]]
- [[Frontend]]