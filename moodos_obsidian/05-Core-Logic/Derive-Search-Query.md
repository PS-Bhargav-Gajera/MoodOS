---
tags: [moodos, core-logic, search, query]
---

# Derive Search Query

Mood-adaptive query construction so searches don't reuse one generic string.

## Source

`_derive_search_query(message, slots, kind, preferences=None)` (`orchestrator.py:138`).

Branches on `kind`:
- **music**: `vibe` from `desired_mood`/message mood words (default `chill`)
  + `music_language` + genre word → e.g. "relaxed gujarati playlist"
  (`orchestrator.py:181-189`).
- **movie**: learned/stated genre + mood word → e.g. "heartwarming calm film"
  — user genre wins, then `preferences.movie_genres`, then the default
  (`orchestrator.py:171-179`). Learned `preferences.movie_language` prefixes
  the base.

`run_pipeline` then appends the least-recently-used stylistic seed via
`_rotate_music_query` (`orchestrator.py:82`) so the same mood doesn't search
the identical string every evening.

This is the function the unit test pins
(`tests/test_pipeline.py::test_music_query_respects_mood_and_varies`) — an
"exhausted/relaxed" prompt must not produce the same query as an
"energetic/celebrate" one. A distinct query is also what lets the repeat
penalty (see [[Ranking and Scoring]], `_apply_repeat_penalty`) see recently
suggested content differently (`_recently_suggested_titles`,
`orchestrator.py:343`).

Called with the already-extracted slots in `run_pipeline`
(`orchestrator.py:2154-2155`) for both `music_q` and `movie_q`.

## Connects to

- [[Intent and Mood Extraction]] · [[Music Language Resolution]]
- [[Ranking and Scoring]] (repeat-penalty hook)
- [[Search Music]] · [[Search Movies]]

## Used by

- [[Request Flow]] · [[Plan Assembly]]