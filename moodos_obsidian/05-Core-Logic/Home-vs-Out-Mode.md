---
tags: [moodos, core-logic, mode]
---

# Home vs Out Mode

Two completely different plan shapes, decided by the extracted `stay_home` flag.

## Decision

`classify_turn` (`nlu.py:145`) matches `HOME_HINTS` first (`nlu.py:24`):
"stay home", "watch at home", "netflix", "no theater/cinema", "ott", "couch",
"binge", "lazy", etc. → `plan + stay_home`. The LLM extractor can also set
`stay_home` ([[Intent and Mood Extraction]]).

## Out mode (default)

Pool includes the Sabarmati-walk seed (`orchestrator.py:1328`), OSM places +
restaurants + cinemas, TMDB movies; plan has physical steps + travel legs;
`action.available=true` (movie booking mock).

## Home mode

- Cinemas skipped (`_cinemas` → `[]`, `orchestrator.py:1275-1278`).
- Movies come from [[Search Home Movies]] (TMDB streaming + watch providers),
  plan steps are `kind: streaming`.
- Plan shape from `_heuristic_plan` stay-home branch
  (`orchestrator.py:431-465`): streaming movie (real runtime pinned by
  [[Movie Metadata and Mood Fit]]) + music; explanation is a cozy-night pitch.
- `action.available=false`; `streaming_movies` exposed in the bundle
  (`orchestrator.py:1409`).

## Connects to

- [[Plan Assembly]] · [[Search Home Movies]] · [[Movie Metadata and Mood Fit]]

## Used by

- [[Request Flow]] · [[Frontend]]