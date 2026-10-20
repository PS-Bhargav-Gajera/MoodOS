---
tags: [moodos, tool, mcp]
---

# Get User Profile

MCP tool `get_user_profile` → `MoodOSMCPServer.get_user_profile`
(`moodos/mcp_server.py:88`).

## Signature

`get_user_profile(user_id: str, query: str, categories: list[str] | None = None) -> dict`
Returns `{user_id, memories}`.

## Behavior

Delegates to `mem0.retrieve(user_id, query, k=8, categories=...)`
(`memory.py:430`, `mem0 = UserMemory()`) which merges Mem0 Cloud hits and the
local TF-IDF fallback, de-duplicating by lowercased text. The memories feed
[[Ranking and Scoring]] (`_pref_match`) and the plan prompt via
`_memory_block` (`orchestrator.py:455`, formatted at `:2298-2304`).

Called inside the pipeline at `orchestrator.py:2102-2107` (categories
`preference/pattern/feedback/episodic`) and recorded as the `mem0` retrieval
path.

## Connects to

- [[Mem0]] · [[Local JSON Memory]]
- [[Ranking and Scoring]]

## Used by

- [[Request Flow]]
- Public MCP surface