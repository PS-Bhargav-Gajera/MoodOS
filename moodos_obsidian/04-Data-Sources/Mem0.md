---
tags: [moodos, data-source, memory, provider]
---

# Mem0

User memory provider (Mem0 Cloud, `MEM0_API_KEY`). Optional — the app falls back
to a local JSON store.

## Source

`memory.py` `UserMemory` → `Mem0Cloud` (`memory.py:72`):
- `_ping` to `api.mem0.ai/v1/ping/` sets `ok` (cheap readiness gate).
- `search` (`memory.py:94`) probes both the v3 and v1 search endpoints.
- `add` (`memory.py:125`) likewise v3 then v1.
- Online again: `_seed_cloud("demo")` (`memory.py:159`) writes a compact
  preference blob if the demo user has nothing (avoids duplicate seeding).

## Merging

`UserMemory.retrieve` (`memory.py:169`) merges Cloud hits + local hits,
de-duplicating by text (cloud first). Returned shape:
`{text, kind, score, source: "mem0-cloud"|"local"}`.

## Feeding the planner

- `memories` reach the map via [[Get User Profile]].
- `_pref_match` in [[Ranking and Scoring]] (`ranking.py:38`) rewards quiet
  cafés/movies/crowd-averse and low-budget picks.
- The plan prompt gets the memory texts (`orchestrator.py:1370`).
- Long-term extraction from feedback: `add_if_long_term` (`memory.py:189`).

## Connects to

- [[Get User Profile]] · [[Route Feedback]] · [[Local JSON Memory]]
- [[Ranking and Scoring]]

## Used by

- [[Request Flow]] · [[Architecture-Overview]] · [[Persistence]]