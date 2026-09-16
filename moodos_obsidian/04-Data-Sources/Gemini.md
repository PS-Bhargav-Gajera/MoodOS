---
tags: [moodos, data-source, agent, llm]
---

# Gemini

Google Gemini (free tier) — the **planning agent** (`GEMINI_API_KEY`).

## Source

`llm.py` `LLMRouter` (`llm.py:23`):
- `_gemini_json` (`llm.py:97`) tries `gemini_plan_model` then each
  `gemini_fallback_models` (comma-separated), using the Google SDK
  `genai.Client`.
- `plan_json` (`llm.py:65`) is Gemini-first, Groq-second.
- Client built lazily when a key exists (`llm.py:34-40`).

## Usage

- Building the experience plan prompt (`orchestrator.py:1369`, `PLAN_PROMPT`).
- Slot extraction when Groq is missing.

**Observed constraint**: the free tier caps ~20 requests/day (429s in
`server.err.log`). On quota exhaustion the planner degrades to Groq or the
deterministic `_heuristic_plan` ([[Plan Assembly]]).

## Connects to

- [[Agent Router]] · [[Plan Assembly]]

## Used by

- [[Request Flow]]