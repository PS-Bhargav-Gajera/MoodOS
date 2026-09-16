---
tags: [moodos, known-issue, bug, copywriting]
---

# Generic step blurbs

**Reported**: some step explanations still read like generic templates instead
of reflecting the actual venue / live order-of-conditions.

## Where the templated strings live (verified)

`_heuristic_plan` (`orchestrator.py:415`) hardcodes several `why` strings
regardless of which venue was picked:

| Step | Template string | Line |
|---|---|---|
| Walk | "Low-effort reset after college; nearby." | `orchestrator.py:477` |
| Rainy pause | "Live weather is wet — skip exposed walking." | `:490` |
| Restaurant (non-priority) | "Nearby restaurant matching your mood." | `:499` |
| Café | "{Venue descriptor} for a low-key evening." | `:533` |
| Stay-home music | "Relaxing background music for a cozy night in." | `:458` |
| Stay-home streaming | "Watch at home — no need to go out. Streaming for free on your existing subscriptions." | `:445` |
| Bare buffer | "Buffer time so the evening feels unhurried and matches your time budget." | `:900` (from `_best_filler`) |

The **LLM plan prompt** (`PLAN_PROMPT`) has the same risk — it is a template
(`orchestrator.py:1369`) and if the planner returns an empty step list the app
silently substitutes the heuristic plan above, so verbatim strings above can
appear even when a movie/cafe did exist.

## What's already contextual

This is a *partial* issue: several blurbs ARE venue/order-aware:
- `_venue_descriptor` (`orchestrator.py:765`) — dessert spot vs quick snack vs
  sit-down restaurant vs café.
- `_best_filler` second-activity `why`
  (`orchestrator.py:877-880`) — named venue + nearest-yet-mood phrasing.
- `_music_why` (`orchestrator.py:793`) — references actual preceding step
  (film/meal/evening) + music language.
- `_finalize_step_order_and_blurbs` (`orchestrator.py:984`) regenerates
  position-dependent blurbs.

## Suggested fix (not yet implemented)

- Pull the picker's real chosen venue (from `_pick_dining` result, not just
  `restaurant["title"]`) into the `why` text for walk/rain/café cases.
- Replace "after college" phrasing for non-student inputs (it's a leftover of
  the demo persona).

## Connects to

- [[Plan Assembly]] · [[Budget Fit Duration]]
- [[Frontend]]

## Used by

- [[00-Home]]