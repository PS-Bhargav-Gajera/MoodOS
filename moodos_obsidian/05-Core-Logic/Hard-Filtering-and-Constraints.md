---
tags: [moodos, core-logic, ranking, constraints]
---

# Hard Filtering and Constraints

Binary eligibility gates before scoring (`moodos/ranking.py`).

## Source

`hard_filter(item, slots, weather, remaining_budget, remaining_min)`
(`ranking.py:94`). Rejects an item when any of these fail:

- **Budget**: `estimated_cost × party_size(slots) > remaining_budget`
  (`ranking.py:98`) — `budget_inr` is the **group total** while candidates
  carry per-person estimates (note: costs come from OSM tier estimates,
  `providers.py:439`; movies use pool defaults ~₹220-260).
- **Time**: `duration_min > remaining_min`.
- **Closed**: `likely_closed_at` set (an `opening_hours` check said closed).
- **Intensity**: low-intensity request vs `intensity: high` item.
- **Crowded**: `crowded` item for a `solo` user.
- **Weather**: outdoor + `needs_clear_weather` item while `rainy`.
- **Distance**: `> 8 km` for place/food, `> 20 km` for movie-with-venue
  (distances from `_distance`, `orchestrator.py:334`).

Item distances are computed in the pool build step
(`orchestrator.py:2288`) before filtering.

## Where it bites

The **budget-fit loop** also refuses to shrink *fixed* durations (movie runtime,
travel, walk/streaming) — a different kind of hard constraint that lives in
[[Budget Fit Duration]] (`_FIXED_KINDS`, `orchestrator.py:857`).

**Note on groups**: `budget_inr` is treated as the group total. The
`party_size` slot is extracted from the message (`nlu.py:193`, accepts 2-50 via
"N friends/people", "family of N") and the None-safe `party_size(slots)` helper
clamps 1..50 (`ranking.py:27`); `hard_filter` (`:98`) and `_food_emphasis`
(`:137`) compare cost as `estimated_cost × party`, and `PLAN_PROMPT`
(`orchestrator.py:435-440`) instructs the LLM to write per-person × party
costs. The durable budget fact is stored per-person when party > 1
(`memory_writer`). Historical note: this ×party math did not exist when
[[Budget Fit Crash]] was filed.

## Connects to

- [[Ranking and Scoring]] · [[Open-Meteo]] · [[OpenStreetMap]]

## Used by

- `run_pipeline` (`orchestrator.py:2289`)
- Unit test `test_hard_filter_drops_club` (`tests/test_pipeline.py:23`)
- [[Request Flow]] · [[Architecture-Overview]]