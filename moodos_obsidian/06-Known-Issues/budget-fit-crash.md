---
tags: [moodos, known-issue, bug, budget, resolved]
---

# Budget Fit Crash (Resolved)

> **Status: FIXED.** This note is kept as history. `_assemble_plan`
> (`orchestrator.py:1793`) contains **no `assert`** anymore: on a budget miss
> the plan is returned best-effort with a `budget_fit` quality dict instead of
> raising. Covered by
> `tests/test_qa_edge.py::test_extreme_durations_no_crash_budget_fit_present`
> and the `budget_fit["within_tolerance"]` assertion in
> `tests/test_pipeline.py:294`.

**Reported**: a group / budget-split / high-energy mood request crashed the
backend with no error surfaced to the user.

## What the user saw (historical)

`app.js` catches any `/api/plan` failure and renders a generic
"Could not build a plan → Oops" card (`app.js:697-713`, card text at
`:706-707`). The real error was a 500 `AssertionError` that only appeared in
the server log.

## Root cause (historical)

`_assemble_plan` ended with a hard assertion:

```
assert abs(dur - requested_min) <= tol + 1, "budget fit failed: ..."
```

There was **no try/except** between this assert and the FastAPI route. The
duration-fit loop ([[Budget Fit Duration]]) converges only when there is always
*some* flexible step to stretch/shave, or a drop target. When those
preconditions broke, the assert fired and the whole plan request died:

- **Over budget with everything fixed**: after dropping the smallest fixed stop
  repeatedly, if the remaining fixed content (movie runtime + travel) still
  exceeded budget, the force-fit branch dropped fixed stops too. If the plan
  ended up empty (or the leftover gap was still > tol+1), the assert tripped.
- **High-energy requests** often produced plans where every physical stop is a
  fixed movie + flexible filler whose per-kind *floor* still overshoots the
  remaining time — the shaving branch stops at the floor and the assert fired
  instead of degrading.
- **"Budget-split" framing**: at the time there was **no group/per-head costing
  in the codebase** (`social` was a label only; costs were single-total
  estimates, see [[Hard Filtering and Constraints]]), so a "₹5000 split among 5
  friends, high energy" prompt was computed as a single ₹5000 / long-hour
  budget, which could also route into the oversized-duration branch above.
  Group budgeting (`party_size` slot, per-person costs × party) has since been
  added.

## Fix (implemented)

- The assert was removed. `_assemble_plan` (`orchestrator.py:1793`) now always
  returns the plan and records a `budget_fit` dict
  (`requested_min` / `actual_min` / `delta_min` / `tolerance_min` /
  `within_tolerance` / `fixed_unchanged`, `:1989-1996`), plus plain-language
  `budget_notes` entries for dropped steps (`:1984`).
- When the fit is still outside tolerance it logs
  `budget fit incomplete ... returning best effort` (`:2010-2014`) instead of
  raising, so `/api/plan` responds 200 with the best-effort plan.
- Group budgets: `party_size` is extracted from the message and per-person
  estimates scale by party ([[Hard Filtering and Constraints]]), so
  "budget-split" prompts no longer over-extend the oversized-duration branch.

## Reproduction cases (now regression tests)

1. Short window (e.g. 2.5 h) + big fixed movie runtime + travel > window.
2. Long budget/hours where only fixed stops remain and flexible floors overshoot.

## Connects to

- [[Budget Fit Duration]] · [[Plan Assembly]] · [[Hard Filtering and Constraints]]
- [[Route Plan]] · [[Frontend]]

## Used by

- [[00-Home]] · [[Search Restaurants]] sibling issue follow-ups
