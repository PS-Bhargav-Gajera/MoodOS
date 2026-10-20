---
tags: [moodos, core-logic, budget, duration]
---

# Budget Fit Duration

Forcing the plan total to equal the requested time (±tolerance) by stretching
or shrinking only **flexible** steps. Money is a separate soft cap (see
[[Hard Filtering and Constraints]]).

## Fixed vs flexible (`orchestrator.py:857`, `:1105`)

- `_FIXED_KINDS = {"movie", "streaming", "walk", "travel"}` (`:857`) — facts
  the loop may **never** rewrite (real movie runtime, travel time).
- Everything else (restaurant/cafe dwell, place, music session, rest) is
  flexible. `_tag_flexibility` stamps the flag (`:1105`, defaults from
  `_kind_flexible`, `:1002`).

## Budget-fit loop (`_assemble_plan`, `orchestrator.py:1793`)

`_duration()`/`_renumber()` helpers (`:1836-1841`), then up to **12 passes**
(`:1843`); `tol = 0.03 * requested_min` (`:1810`).

- **Under budget** (`diff < 0`): extend music toward its `_DUR_CAPS` cap of
  30 min (a, `:1851-1860`), stretch the longest flexible main stop (b, capped
  by `_DUR_CAPS`, `:1861-1874`), prefer a *meaningful* filler via
  `_best_filler` (`orchestrator.py:1414`) that returns a wind-down music leg, a
  short second activity, or only-as-last-resort a bare "rest" buffer (c,
  `:1875-1900`), then distribute the leftover across ALL flexible steps, each
  up to its per-kind cap, and finally absorb any residual into capped pacing
  buffers via `_add_buffer_steps` (d, `:1901-1920`).
- **Over budget** (`diff > 0`): never shrink fixed — shave the longest
  shavable physical stop down to a per-kind floor (`restaurant/cafe/food 40`,
  `place 20`, `indoor 15`, `:1928-1938`), or **drop** the lowest-priority
  physical stop when everything left is fixed and still over, appending a
  plain-language `budget_notes` entry (`:1939-1953`).

Post-loop force-fit (`:1961-1982`) handles leftovers (shave a flexible step,
or drop a fixed stop with a note); buffers are collapsed/limited
(`:1956-1957`); then `budget_fit` stats are recorded (`:1989-1996`):

```python
plan["budget_fit"] = {
    "requested_min": ..., "actual_min": ..., "delta_min": ...,
    "tolerance_min": ..., "within_tolerance": abs(dur - requested_min) <= tol + 1,
    "fixed_unchanged": True,
}
```

**No assert runs.** If the loop never converged, `_assemble_plan` logs
`budget fit incomplete ... returning best effort` (`:2010-2014`) and returns
the plan anyway, so the request degrades instead of crashing (this used to be
an `AssertionError` 500 — see the resolved [[Budget Fit Crash]]).

## Connects to

- [[Plan Assembly]] · [[Hard Filtering and Constraints]]

## Used by

- `run_pipeline` (`orchestrator.py:2028`), called at `:2319`
- [[Request Flow]] · [[Route Plan]]
