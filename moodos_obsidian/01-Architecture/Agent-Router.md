---
tags: [moodos, architecture, agents, llm]
---

# Agent Router

MoodOS uses two free LLM providers with a strict role split
(`moodos/llm.py`, `LLMRouter`).

## Split

| Task | Primary | Model | Method |
|---|---|---|---|
| Slot/intent extraction | Groq | `groq_fast_model` (e.g. `openai/gpt-oss-20b`) | `extract_json` (`llm.py:50`) |
| Plan construction | Gemini | `gemini_plan_model` + fallbacks (`gemini-2.5-flash` etc.) | `plan_json` (`llm.py:65`) |

Both are behind `EXTRACT_SYSTEM` (`llm.py:16`): "return ONLY valid JSON".
Parsing is lenient via `parse_json_object` (`jsonutil.py:8`) which strips
code fences and extracts the first `{...}` block.

## Fallback chain

- **Extraction**: Groq → Gemini → `{}`. The caller (`nlu.extract_intent`,
  `nlu.py:254`) merges any LLM slots over the deterministic
  `heuristic_extract` base ([[Intent and Mood Extraction]]).
- **Planning**: Gemini → Groq (reason model, then fast model) → `{}`. The
  caller (`_plan_with_budget`, `orchestrator.py:222`) falls back to
  `_heuristic_plan` ([[Plan Assembly]]).
- Provider objects are created lazily and only when a key is configured
  (`llm.py:27-40`). The app runs fully without keys.
- Every successful result is tagged with `_agent` and `_model`; the bundle
  surface them under `agents` (`orchestrator.py:1425-1431`).

## Rate limits observed

The Gemini free tier caps ~20 requests/day; `server.err.log` shows 429s, after
which planning silently degrades to heuristics or Groq.

## Connects to

- [[Intent and Mood Extraction]] · [[Plan Assembly]] · [[Direct Chat]]
- [[Groq]] · [[Gemini]]

## Used by

- [[Request Flow]]
- `nlu.py`, `orchestrator.py`, `chat.py`