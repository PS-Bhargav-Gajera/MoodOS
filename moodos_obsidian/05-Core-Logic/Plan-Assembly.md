---
tags: [moodos, core-logic, planning]
---

# Plan Assembly

Turning scored candidates into an ordered evening plan
(`moodos/orchestrator.py`).

## Planners (`orchestrator.py`)

1. **LLM planner** — `_plan_with_budget(prompt, ranked, slots, weather)`
   (`orchestrator.py:472`), run on a daemon thread with a hard
   `thread.join(timeout=35.0)` budget (`:479-493`); prompt built from
   `PLAN_PROMPT` (`orchestrator.py:416`, formatted at `:2298-2304`). JSON
   parsed leniently ([[Agent Router]]).
2. **Heuristic planner** — `_heuristic_plan(ranked, slots, weather)`
   (`orchestrator.py:669`) used when the LLM returns no steps: walk-or-rainy
   opening, restaurant (food-priority aware) or café, movie (via
   `_pick_best_movie`, `orchestrator.py:535`), wind-down music; stay-home mode
   gets streaming + music. Costs are per-person estimate × `party_size`
   (restaurant cap = ₹500 × party). Titles/`why` strings here are the source
   of the [[Generic step blurbs]] issue.

Common fixes applied on top:

- `_ensure_explicit_movie` (`orchestrator.py:1112`) — an explicit "watch a
  movie" request never silently drops the film.
- `_normalize_movie_steps` (`orchestrator.py:1178`) — pins REAL runtimes +
  `flexible: False` + showtime disclaimers ([[Movie Metadata and Mood Fit]]).
- `_attach_coordinates_to_steps` (`orchestrator.py:1252`),
  `_insert_travel_legs` (`orchestrator.py:1646`), `_travel_leg_for`
  (`orchestrator.py:1601`) — walk / drive / transit legs with distance + ₹cost.
- `_finalize_step_order_and_blurbs` (`orchestrator.py:1694`) — renumbers steps
  and fixes position-dependent music blurbs.
- `_attach_music_tracks` (`orchestrator.py:1317`) — real tracks on music steps.

## Output plan shape

`steps[]` with `kind`, `title`, `duration_min`, `cost_inr`, `flexible`, `why`,
lat/lon, and per-kind extras (runtime/venue for movies, `tracks` for music).
Plus `total_duration_min`, `total_cost_inr`, `explanation`,
`budget_fit`, `budget_notes`, `requested_minutes`, and a `budget` object
(`budget_inr`, `party_size`, `total_cost_inr`, `over_budget`,
`orchestrator.py:2000-2009`).

## Connects to

- [[Budget Fit Duration]] · [[Agent Router]] · [[Movie Metadata and Mood Fit]]
- [[Hard Filtering and Constraints]]

## Used by

- `run_pipeline` (`orchestrator.py:2305-2319`)
- [[Request Flow]] · [[Route Plan]]