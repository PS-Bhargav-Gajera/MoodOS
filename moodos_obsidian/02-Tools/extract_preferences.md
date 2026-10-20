---
tags: [moodos, tool, mcp]
---

# Extract Preferences

MCP tool `extract_preferences` → `MoodOSMCPServer.extract_preferences`
(`moodos/mcp_server.py:78`).

## Signature

`extract_preferences(message: str) -> dict`
Returns `implicit_preferences`, `budget_inr`, `duration_hours`, `social`,
`intensity`.

## Behavior

Same `extract_intent` source as [[Analyze Mood]]; projects only the
preference-shaped slots (budget, time, social, intensity). The live pipeline
builds an equivalent `prefs` dict directly from `slots`
(`orchestrator.py:2093-2100`, which also carries `party_size`) rather than
calling this tool.

## Connects to

- [[Intent and Mood Extraction]]
- [[Ranking and Scoring]] (these slots feed weights)

## Used by

- Public MCP surface
- [[Route Prompts]]