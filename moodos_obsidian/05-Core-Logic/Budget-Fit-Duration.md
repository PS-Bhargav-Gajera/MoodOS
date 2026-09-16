---
tags: [moodos, core-logic, budget, duration]
---

# Budget Fit Duration

Forcing the plan total to equal the requested time (±tolerance) by stretching
or shrinking only **flexible** steps. Money is a separate soft cap (see
[[Hard Filtering and Constraints]]).

## Fixed vs flexible (`orchestrator.py:593-615`)

- `_FIXED_KINDS = {"movie", "streaming", "walk", "travel"}` (`:600`) — facts
  the loop may **never** rewrite (real movie runtime, travel time).
- Everything else (restaurant/cafe dwell, place, music session, rest) is
  flexible. `_tag_flexibility` stamps the flag `:611`.

## Budget-fit loop (`_assemble_plan`, `orchestrator.py:1014`)

`_duration()`/`_renumber()` helpers, then up to **12 passes**
(`:1046`):

- **Under budget** (`diff < 0`): extend music up to a 180-min cap (a),
  stretch the longest flexible main stop (b), prefer a *meaningful* filler via
  `_best_filler` (`orchestrator.py:819`) that returns a wind-down music leg, a
  short second activity, or only-as-last-resort a bare "rest" buffer (c), then
  force-stretch the longest flexible step (d).
- **Over budget** (`diff > 0`): never shrink fixed — shave the long flexible
  stop down to a per-kind floor (`restaurant/cafe/food 40`, `place 20`,
  `indoor 15`), or **drop** the lowest-priority physical stop when everything
  left is fixed and still over, appending a plain-language `budget_notes`
  entry (`:1123-1137`).

Post-loop force-fit (`:1144-1165`) handles leftovers; then `budget_fit` stats
are computed and **the assert runs** (`orchestrator.py:1180`):

```python
assert abs(dur - requested_min) <= tol + 1, f"budget fit failed: ..."
```

## Crash risk

The assert has **no try/except anywhere up the call chain**. If duration can
never converge in the tolerance window — e.g. a budget so large that step
dropping empties the plan, or shaving floors that still overshoot — the
`AssertionError` escapes `run_pipeline`, `/api/plan` returns 500, and the
frontend shows only the generic "Oops" ([[Budget Fit Crash]]).

## Connects to

- [[Plan Assembly]] · [[Hard Filtering and Constraints]]

## Used by

- `run_pipeline` (`orchestrator.py:1379`)
- [[Request Flow]] · [[Route Plan]]