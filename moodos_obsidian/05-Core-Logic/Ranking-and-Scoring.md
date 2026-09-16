---
tags: [moodos, core-logic, ranking]
---

# Ranking and Scoring

Scoring every candidate so the plan gets the best fit
(`moodos/ranking.py`).

## Weights (`ranking.py:6`)

```
mood 0.28 | preference 0.22 | food 0.20 | context 0.16
review 0.12 | distance_penalty 0.12 | cross 0.10 | novelty 0.08
```

## Components

- `_mood_match` (`ranking.py:20`) — hard-minus when intensity low but item
  high; keyword overlap with desired/current mood for a bonus.
- `_pref_match` (`ranking.py:38`) — memory-aware (quiet café, movies, crowd,
  low budget signals from [[Mem0]]).
- `_food_emphasis` (`ranking.py:80`) — when `food_priority` is set, prefers a
  substantial sit-down (mid/premium) if budget ≥ 800, instead of a cheap snack.
- `review` — `vote`/`review_quality` clamped 0.3-1.0.
- `distance_pen` — `min(dist/12, 1)`, `0.15` when unknown.
- `score_item(...)` (`ranking.py:106`) — the linear blend.

## Ordering

- `hard_filter` first ([[Hard Filtering and Constraints]]).
- `_apply_repeat_penalty` (`orchestrator.py:163`) — suppresses repeats of
  recently suggested titles for the same music query.
- `rerank` (`ranking.py:132`) — interleaves by first-seen kind so the final
  list isn't one-kind-dominated.

## Connects to

- [[Hard Filtering and Constraints]] · [[Mem0]]
- [[Review Classification]] (review signal)

## Used by

- `run_pipeline` (`orchestrator.py:1357-1367`)
- `_pick_dining` (`orchestrator.py:387`) · `_pick_best_movie`
  (`orchestrator.py:284`)