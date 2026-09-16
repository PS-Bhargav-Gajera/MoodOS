---
tags: [moodos, tool, mcp]
---

# Get User Profile

MCP tool `get_user_profile` → `MoodOSMCPServer.get_user_profile`
(`moodos/mcp_server.py:85`).

## Signature

`get_user_profile(user_id: str, query: str) -> dict`
Returns `{user_id, memories}`.

## Behavior

Delegates to `mem0.retrieve(user_id, query)` (`memory.py:169`) which merges
Mem0 Cloud calls and the local TF-IDF fallback, de-duplicating by text.
The memories feed [[Ranking and Scoring]] (`_pref_match`)
and the plan prompt (`orchestrator.py:1370`).

Called inside the pipeline at `orchestrator.py:1222` and recorded as the
`mem0` retrieval path.

## Connects to

- [[Mem0]] · [[Local JSON Memory]]
- [[Ranking and Scoring]]

## Used by

- [[Request Flow]]
- Public MCP surface