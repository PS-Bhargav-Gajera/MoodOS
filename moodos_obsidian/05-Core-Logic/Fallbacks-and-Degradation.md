---
tags: [moodos, core-logic, fallback, resilience]
---

# Fallbacks and Degradation

How the app stays functional with no keys, no quota, and flaky providers.

## LLM ([[Agent Router]])

- Every call is HTTP-bounded: `LLM_TIMEOUT_S = 25.0` (`llm.py:28`; Groq
  `timeout=25.0, max_retries=0`, Gemini `http_options={"timeout": 25000}`) —
  nothing can hang indefinitely, and the planner adds its own 35 s
  `thread.join` budget (`orchestrator.py:489`).
- Extraction: Groq → Gemini → `{}` (heuristic base wins).
- Planning: Gemini → Groq(reason→fast) → `_heuristic_plan`.
- Chat replies: LLM → help reply.

## Providers

| Provider | Fallback |
|---|---|
| Weather (Open-Meteo) | honest `source: "unavailable"` dict, never-rainy (`providers.py:20`); the tool panel only claims live when it was (`orchestrator.py:2018`) |
| TMDB search | local RAG movie docs ([[Search Movies]]); movie pool/est runtimes |
| Spotify search | **Spotify-only — honest empty list, no iTunes fallback** ([[Search Music]], `providers.py:840-855`) |
| Mem0 Cloud | local JSON memory (merged when Cloud works) |
| OSM Overpass | mirror retries + circuit breaker inside one wall-clock budget (`providers.py:225-279`); Nominatim search fallback (`_nominatim_nearby`, `providers.py:765`) for nearby places |

## Pipeline-level

- Every parallel lookup is `try/except`: one provider's failure can't kill the
  plan (`orchestrator.py:2204-2208`).
- If `pool` is empty, `hard_filter` produces nothing → `_heuristic_plan` still
  builds a template evening ([[Generic step blurbs]]).
- **Adaptive knowledge fallback**: when RAG confidence < `0.12`, the pipeline
  fetches DuckDuckGo snippets, ingests them into the knowledge store, and
  retries retrieval (`orchestrator.py:2223-2239`, [[Knowledge RAG Store]]).

## Not covered

- A failed or timed-out provider call still degrades to an empty list for that
  source — Overpass and TMDB retry internally (mirrors/breaker; 12 attempts,
  `providers.py:1213`), but there is no user-facing retry affordance.
- Budget-fit misses no longer crash: `_assemble_plan` returns a best-effort
  plan with `budget_fit.within_tolerance=false` instead (see the resolved
  [[Budget Fit Crash]]).

## Connects to

- [[Agent Router]] · [[Search Music]] · [[Search Movies]] · [[Knowledge RAG Store]] · [[DuckDuckGo]]

## Used by

- [[Architecture-Overview]] · [[Request Flow]]
