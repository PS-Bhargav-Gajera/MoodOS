---
tags: [moodos, tool, mcp]
---

# Analyze Reviews

MCP tool `analyze_reviews` → `MoodOSMCPServer.analyze_reviews`
(`moodos/mcp_server.py:162`).

## Signature

`analyze_reviews(title: str, text: str) -> dict`
Returns `{title, aspects, summary}` where `aspects` = `{story, pacing, tone}`.

## Behavior

Keyword-rule classification, no LLM: looks for story/character words
(`story`, `character`, `heart`), pacing words (`slow`, `gentle`), and calming
tone words (`calm`, `quiet`, `warm`, `comfort`). Short text stays as `summary`
(280 chars).

Applied to the top-4 ranked movie/place candidates after planning
(`orchestrator.py:2327-2330`); the result is exposed in the bundle as
`reviews` and rendered for the movie/venue steps. This is the 
[[Review Classification]] core-logic note backed by the tool.

## Connects to

- [[Review Classification]]

## Used by

- `run_pipeline` (`orchestrator.py:2327-2330`)
- Public MCP surface