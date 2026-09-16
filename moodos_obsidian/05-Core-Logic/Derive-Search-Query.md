---
tags: [moodos, core-logic, search, query]
---

# Derive Search Query

Mood-adaptive query construction so searches don't reuse one generic string.

## Source

`_derive_search_query(message, slots, kind)` (`orchestrator.py:28`).

Branches on `kind`:
- **music**: builds from `desired_mood`/`current_mood`/`intensity` +
  `music_language` (e.g. "relaxed" + gujarati → "calm gujarati songs").
- **movie**: builds from mood/trajectory for the film search.

This is the function the unit test pins
(`tests/test_pipeline.py::test_music_query_respects_mood_and_varies`) — an
"exhausted/relaxed" prompt must not produce the same query as an
"energetic/celebrate" one. A distinct query is also what lets the repeat
penalty (see [[Ranking and Scoring]], `_apply_repeat_penalty`) see recently
suggested content differently (`_recently_suggested_titles`,
`orchestrator.py:159`).

Called with the already-extracted slots in `run_pipeline`
(`orchestrator.py:1254-1255`) for both `music_q` and `movie_q`.

## Connects to

- [[Intent and Mood Extraction]] · [[Music Language Resolution]]
- [[Ranking and Scoring]] (repeat-penalty hook)
- [[Search Music]] · [[Search Movies]]

## Used by

- [[Request Flow]] · [[Plan Assembly]]