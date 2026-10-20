---
tags: [moodos, tool, mcp]
---

# Analyze Mood

MCP tool `analyze_mood` → `MoodOSMCPServer.analyze_mood`
(`moodos/mcp_server.py:67`).

## Signature

`analyze_mood(message: str) -> dict`
Returns `current_mood`, `desired_mood`, `mood_intensity`,
`mood_trajectory`, `emotional_constraints`, `agent`.

## Behavior

Runs `extract_intent(message)` (`nlu.py:269`) and returns only the emotional
slots. Extraction pipeline: [[Intent and Mood Extraction]].

**Note**: the live plan does **not** call this tool — `run_pipeline` reuses the
already-extracted `slots` to build the `mood` dict (`orchestrator.py:2085-2092`)
to avoid a second LLM round-trip. This tool is exposed for external MCP clients
and listed under `/api/prompts`.

## Connects to

- [[Intent and Mood Extraction]]
- [[Groq]] · [[Gemini]]

## Used by

- Public MCP surface (`/api/prompts`, `app.py:372-374`)
- [[Route Prompts]]