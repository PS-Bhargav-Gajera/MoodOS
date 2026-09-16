---
tags: [moodos, known-issue, bug, budget]
---

# Budget Fit Crash

**Reported**: a group / budget-split / high-energy mood request crashes the
backend with no error surfaced to the user.

## What the user sees

`app.js` catches any `/api/plan` failure and renders a generic
"Could not build a plan → Oops" card (`app.js:583-593`). The real error is a
500 `AssertionError` that only appears in the server log.

## Root cause (verified in code)

`_assemble_plan` ends with a hard assertion
(`orchestrator.py:1180-1181`):

```
assert abs(dur - requested_min) <= tol + 1, "budget fit failed: ..."
```

There is **no try/except** between this assert and the FastAPI route. The
duration-fit loop ([[Budget Fit Duration]]) is guaranteed to converge only when
there is always *some* flexible step to stretch/shave, or a drop target. When
those preconditions break, the assert fires and the whole plan request dies:

- **Over budget with everything fixed**: after dropping the smallest fixed stop
  repeatedly (`orchestrator.py:1123-1137`), if the remaining fixed content
  (movie runtime + travel) still exceeds budget, the force-fit branch
  (`:1153-1165`) drops fixed stops too. If the plan ends up empty (or the
  leftover gap is still > tol+1), the assert trips.
- **High-energy requests** often produce plans where every physical stop is a
  fixed movie + flexible filler whose per-kind *floor* still overshoots the
  remaining time — the shaving branch (`:1112-1122`) stops at the floor and the
  assert fires instead of degrading.
- **"Budget-split" framing**: there is **no group/per-head costing in the
  codebase** at all (`social` is a label only; costs are single-total estimates,
  see [[Hard Filtering and Constraints]]). So a "₹5000 split among 5 friends,
  high energy" prompt is computed as a single ₹5000 / long-hour budget, which
  can also route into the oversized-duration branch above.

## Why "no error surfaced"

`handle_message`/`run_pipeline` never catch `AssertionError`; FastAPI returns
500; the frontend maps every non-OK response to the same generic "Oops".

## Suggested fix (not yet implemented)

- Replace the assert with a graceful exit: cap requested duration, drop-and-log
  steps to fit, or return a plan with `budget_fit.within_tolerance=false` + a
  plain-language `budget_notes` entry instead of raising.
- Optionally interpret `social` as a headcount to scale per-person ticket/meal
  estimates, so "group" budgets behave as split totals.

## Reproduction cases

1. Short window (e.g. 2.5 h) + big fixed movie runtime + travel > window.
2. Long budget/hours where only fixed stops remain and flexible floors overshoot.

## Connects to

- [[Budget Fit Duration]] · [[Plan Assembly]] · [[Hard Filtering and Constraints]]
- [[Route Plan]] · [[Frontend]]

## Used by

- [[00-Home]] · [[Search Restaurants]] sibling issue follow-ups