---
tags: [moodos, data-source, agent, llm]
---

# Groq

Free-tier LLM provider — the **fast extraction** agent (`GROQ_API_KEY`).

## Source

`llm.py` `LLMRouter` (`llm.py:31`):
- `extract_json` (`llm.py:65`) — uses `settings.groq_fast_model`
  (default `openai/gpt-oss-20b`, `config.py:25`; override with
  `GROQ_FAST_MODEL`), temperature 0.2.
- `plan_json` fallback (`llm.py:80-93`) — `groq_reason_model`
  (`openai/gpt-oss-120b`) then the fast model.
- Client built lazily only when a key exists (`llm.py:35-45`), with a hard
  **25 s timeout and zero retries**: `LLM_TIMEOUT_S = 25.0` (`llm.py:28`),
  `Groq(api_key=..., timeout=25.0, max_retries=0)` (`llm.py:39-43`) — without
  this Groq would retry for ~180 s per leg.

## Usage

- Slot extraction (`nlu.extract_intent` at `nlu.py:269-270`,
  [[Intent and Mood Extraction]]).
- Chat replies (`chat.py:98`).
- Plan construction when Gemini is unavailable ([[Agent Router]]).

Failures degrade gracefully: wrapped in try/except, logged, and the app falls
back to Gemini or heuristics — the app runs with no keys at all.

## Connects to

- [[Agent Router]] · [[Intent and Mood Extraction]] · [[Direct Chat]]

## Used by

- [[Request Flow]]