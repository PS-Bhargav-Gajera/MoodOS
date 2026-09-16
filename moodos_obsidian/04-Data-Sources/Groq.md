---
tags: [moodos, data-source, agent, llm]
---

# Groq

Free-tier LLM provider — the **fast extraction** agent (`GROQ_API_KEY`).

## Source

`llm.py` `LLMRouter` (`llm.py:23`):
- `extract_json` (`llm.py:50`) — uses `settings.groq_fast_model`
  (e.g. `openai/gpt-oss-20b`), temperature 0.2.
- `plan_json` fallback (`llm.py:65`) — reason model, then fast model.
- Client built lazily only when a key exists (`llm.py:27-33`).

## Usage

- Slot extraction (`nlu.extract_intent`, [[Intent and Mood Extraction]]).
- Chat replies (`chat.py:92`).
- Plan construction when Gemini is unavailable ([[Agent Router]]).

Failures degrade gracefully: wrapped in try/except, logged, and the app falls
back to Gemini or heuristics — the app runs with no keys at all.

## Connects to

- [[Agent Router]] · [[Intent and Mood Extraction]] · [[Direct Chat]]

## Used by

- [[Request Flow]]