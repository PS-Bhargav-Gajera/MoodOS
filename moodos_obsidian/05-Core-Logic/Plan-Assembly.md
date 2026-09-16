---
tags: [moodos, core-logic, planning]
---

# Plan Assembly

Turning scored candidates into an ordered evening plan
(`moodos/orchestrator.py`).

## Planners (`orchestrator.py`)

1. **LLM planner** — `_plan_with_budget(prompt, ranked, slots, weather)`
   (`orchestrator.py:222`), run so it completes within a hard timeout via
   `ThreadPoolExecutor` (`:232`); prompt built from `PLAN_PROMPT`
   (`:1369-1375`). JSON parsed leniently ([[Agent Router]]).
2. **Heuristic planner** — `_heuristic_plan(ranked, slots, weather)`
   (`orchestrator.py:415`) used when the LLM returns no steps: walk-or-rainy
   opening, restaurant (food-priority aware) or café, movie (via
   `_pick_best_movie`, `orchestrator.py:284`), wind-down music; stay-home mode
   gets streaming + music. Titles/`why` strings here are the source of the
   [[Generic step blurbs]] issue.

Common fixes applied on top:

- `_ensure_explicit_movie` (`orchestrator.py:618`) — an explicit "watch a
  movie" request never silently drops the film.
- `_normalize_movie_steps` (`orchestrator.py:683`) — pins REAL runtimes +
  `flexible: False` + showtime disclaimers ([[Movie Metadata and Mood Fit]]).
- `_attach_coordinates_to_steps` (`orchestrator.py:740`), `_insert_travel_legs`
  (`orchestrator.py:951`), `_travel_leg_for` (`orchestrator.py:926`) — walk /
  drive / transit legs with distance + ₹cost.
- `_finalize_step_order_and_blurbs` (`orchestrator.py:984`) — renumbers steps
  and fixes position-dependent music blurbs.
- `_attach_music_tracks` (`orchestrator.py:805`) — real tracks on music steps.

## Output plan shape

`steps[]` with `kind`, `title`, `duration_min`, `cost_inr`, `flexible`, `why`,
lat/lon, and per-kind extras (runtime/venue for movies, `tracks` for music).
Plus `total_duration_min`, `total_cost_inr`, `explanation`,
`budget_fit`, `budget_notes`, `requested_minutes`.

## Connects to

- [[Budget Fit Duration]] · [[Agent Router]] · [[Movie Metadata and Mood Fit]]
- [[Hard Filtering and Constraints]]

## Used by

- `run_pipeline` (`orchestrator.py:1376-1384`)
- [[Request Flow]] · [[Route Plan]]