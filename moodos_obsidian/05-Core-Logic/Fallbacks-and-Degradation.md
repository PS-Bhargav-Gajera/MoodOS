---
tags: [moodos, core-logic, fallback, resilience]
---

# Fallbacks and Degradation

How the app stays functional with no keys, no quota, and flaky providers.

## LLM ([[Agent Router]])

- Extraction: Groq → Gemini → `{}` (heuristic base wins).
- Planning: Gemini → Groq(reason→fast) → `_heuristic_plan`.
- Chat replies: LLM → help reply.

## Providers

| Provider | Fallback |
|---|---|
| Spotlight | none — empty list |
| TMDB search | local RAG movie docs ([[Search Movies]]); movie pool/est runtimes |
| Spotify search (403 Premium) | iTunes pool [[Search Music]] |
| Mem0 Cloud | local JSON memory (merged when Cloud works) |
| OSM Overpass | Nominatim search fallback (`_nominatim_nearby`) |

## Pipeline-level

- Every parallel lookup is `try/except`: one provider's failure can't kill the
  plan (`orchestrator.py:1299-1301`).
- If `pool` is empty, `hard_filter` produces nothing → `_heuristic_plan` still
  builds a template evening ([[Generic step blurbs]]).
- **Adaptive knowledge fallback**: when RAG confidence < `0.12`, the pipeline
  fetches DuckDuckGo snippets, ingests them into the knowledge store, and
  retries retrieval (`orchestrator.py:1313-1326`, [[Knowledge RAG Store]]).

## Not covered

- **No graceful path for a budget-fit failure**: the assert in
  [[Budget Fit Duration]] becomes an unhandled 500 — see [[Budget Fit Crash]].
- No retry logic on partial provider timeouts (they just return `[]`).

## Connects to

- [[Agent Router]] · [[Search Music]] · [[Search Movies]] · [[Knowledge RAG Store]] · [[DuckDuckGo]]

## Used by

- [[Architecture-Overview]] · [[Request Flow]]