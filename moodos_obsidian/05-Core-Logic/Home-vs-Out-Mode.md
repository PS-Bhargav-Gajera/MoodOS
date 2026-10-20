---
tags: [moodos, core-logic, mode]
---

# Home vs Out Mode

Two completely different plan shapes, decided by the extracted `stay_home` flag.

## Decision

The flag that shapes the plan is `slots["stay_home"]`, read in `run_pipeline`
(`orchestrator.py:2136`). It is set by `heuristic_extract` matching
`HOME_HINTS` (`nlu.py:24, 228`): "stay home", "watch at home", "netflix",
"no theater/cinema", "ott", "couch", "binge", "lazy", etc., and can be
overridden by the LLM extractor (`EXTRACT_PROMPT`, `nlu.py:174`,
[[Intent and Mood Extraction]]). `classify_turn` (`nlu.py:145`) matches the
same hints first and tags the turn `plan + stay_home`, but it only gates
chat-vs-plan routing in `handle_message` (`orchestrator.py:507-510`).

## Out mode (default)

Pool includes a walk seed (`orchestrator.py:2241`, a generic "20-minute walk
along a quiet stretch near {city}" — used **only** when no real Overpass park
is found nearby, `:2261-2265`), OSM places + restaurants + cinemas, TMDB
movies; plan has physical steps + travel legs;
`action.available=true` (movie booking mock, `orchestrator.py:2382-2387`).

## Home mode

- Cinemas skipped (`_cinemas` → `[]`, `orchestrator.py:2183-2186`).
- Movies come from [[Search Home Movies]] (TMDB streaming + watch providers,
  `orchestrator.py:2165-2169`), plan steps are `kind: streaming`.
- Plan shape from `_heuristic_plan` stay-home branch
  (`orchestrator.py:686-722`): streaming movie (real runtime pinned by
  [[Movie Metadata and Mood Fit]]) + music; explanation is a cozy-night pitch.
- `action.available=false`; `streaming_movies` exposed in the bundle
  (`orchestrator.py:2351`).

## Connects to

- [[Plan Assembly]] · [[Search Home Movies]] · [[Movie Metadata and Mood Fit]]

## Used by

- [[Request Flow]] · [[Frontend]]