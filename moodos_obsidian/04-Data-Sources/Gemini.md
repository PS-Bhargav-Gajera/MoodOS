---
tags: [moodos, data-source, agent, llm]
---

# Gemini

Google Gemini (free tier) — the **planning agent** (`GEMINI_API_KEY`).

## Source

`llm.py` `LLMRouter` (`llm.py:31`):
- `_gemini_json` (`llm.py:112`) tries `gemini_plan_model` then each
  `gemini_fallback_models` (comma-separated, defaults in `config.py:27-31`;
  overridable via `GEMINI_PLAN_MODEL` / `GEMINI_FALLBACK_MODELS` in
  `.env.example`), using the Google SDK `genai.Client`.
- `plan_json` (`llm.py:80`) is Gemini-first, Groq-second.
- Client built lazily when a key exists (`llm.py:46-55`), bounded to a
  **25 s HTTP timeout**: `LLM_TIMEOUT_S = 25.0` (`llm.py:28`) passed as
  `http_options={"timeout": 25000}` (`llm.py:52`) — Gemini has no default
  timeout, so every call is capped.

## Usage

- Building the experience plan prompt: `PLAN_PROMPT` (`orchestrator.py:416`)
  is formatted at `orchestrator.py:2298` and run by `_plan_with_budget`
  (`orchestrator.py:472`, `router.plan_json` at 483) under a 35 s budget
  (`orchestrator.py:489`).
- Slot extraction when Groq is missing.

**Observed constraint**: the free tier caps ~20 requests/day (429s in
`server.err.log`). On quota exhaustion the planner degrades to Groq or the
deterministic `_heuristic_plan` ([[Plan Assembly]]).

## Connects to

- [[Agent Router]] · [[Plan Assembly]]

## Used by

- [[Request Flow]]