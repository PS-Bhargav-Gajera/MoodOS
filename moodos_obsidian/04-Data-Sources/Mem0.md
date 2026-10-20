---
tags: [moodos, data-source, memory, provider]
---

# Mem0

User memory provider (Mem0 Cloud, `MEM0_API_KEY`). Optional — the app falls back
to a local JSON store.

## Source

`memory.py` `UserMemory` → `Mem0Cloud` (`memory.py:195`, built at
`memory.py:412`):
- `_ping` (`memory.py:208`) to `api.mem0.ai/v1/ping/` sets `ok` (cheap
  readiness gate).
- `search` (`memory.py:242`) probes both the v3 and v1 search endpoints.
- `add` (`memory.py:289`) likewise v3 then v1.
- Online at startup: `_seed_cloud("demo")` (`memory.py:420`, called from
  `memory.py:413-414`) writes a compact preference blob if the demo user has
  nothing (avoids duplicate seeding).

## Merging

`UserMemory.retrieve` (`memory.py:430`) merges Cloud hits + local hits,
de-duplicating by text (cloud first). Returned shape:
`{text, kind, score, source: "mem0-cloud"|"local"}`.

## Feeding the planner

- `memories` reach the map via [[Get User Profile]].
- `_pref_match` in [[Ranking and Scoring]] (`ranking.py:59`) rewards quiet
  cafés/movies/crowd-averse and low-budget picks.
- The plan prompt gets the memory texts (`memory=_memory_block(...)`,
  `orchestrator.py:455`, formatted at `orchestrator.py:2300`).
- Long-term extraction from feedback: `add_if_long_term` (`memory.py:460`).

## Connects to

- [[Get User Profile]] · [[Route Feedback]] · [[Local JSON Memory]]
- [[Ranking and Scoring]]

## Used by

- [[Request Flow]] · [[Architecture-Overview]] · [[Persistence]]