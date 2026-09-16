---
tags: [moodos, core-logic, ranking, constraints]
---

# Hard Filtering and Constraints

Binary eligibility gates before scoring (`moodos/ranking.py`).

## Source

`hard_filter(item, slots, weather, remaining_budget, remaining_min)`
(`ranking.py:56`). Rejects an item when any of these fail:

- **Budget**: `estimated_cost > remaining_budget` (note: costs come from OSM
  tier estimates, `providers.py:250`; movies use pool defaults ~₹220-260).
- **Time**: `duration_min > remaining_min`.
- **Closed**: `likely_closed_at` set (an `opening_hours` check said closed).
- **Intensity**: low-intensity request vs `intensity: high` item.
- **Crowded**: `crowded` item for a `solo` user.
- **Weather**: outdoor + `needs_clear_weather` item while `rainy`.
- **Distance**: `> 8 km` for place/food, `> 20 km` for movie-with-venue
  (distances from `_distance`, `orchestrator.py:150`).

Item distances are computed in the pool build step
(`orchestrator.py:1359`) before filtering.

## Where it bites

The **budget-fit loop** also refuses to shrink *fixed* durations (movie runtime,
travel, walk/streaming) — a different kind of hard constraint that lives in
[[Budget Fit Duration]] (`_FIXED_KINDS`, `orchestrator.py:600`).

**Note on groups**: the system has a `social` slot (solo/friends/family/date)
but **no per-head cost math** — there is no budget-splitting or
per-person costing anywhere in the code. A "group night" request is treated as
a single total budget. See [[Budget Fit Crash]].

## Connects to

- [[Ranking and Scoring]] · [[Open-Meteo]] · [[OpenStreetMap]]

## Used by

- `run_pipeline` (`orchestrator.py:1360`)
- Unit test `test_hard_filter_drops_club` (`tests/test_pipeline.py:19`)
- [[Request Flow]] · [[Architecture-Overview]]