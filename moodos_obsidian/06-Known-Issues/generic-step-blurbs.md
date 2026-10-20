---
tags: [moodos, known-issue, bug, copywriting]
---

# Generic step blurbs

**Reported**: some step explanations still read like generic templates instead
of reflecting the actual venue / live order-of-conditions.

## Where the templated strings live (verified)

`_heuristic_plan` (`orchestrator.py:669`) hardcodes several `why` strings
regardless of which venue was picked:

| Step | Template string | Line |
|---|---|---|
| Walk | "Low-effort reset after college; nearby." | `orchestrator.py:734` |
| Rainy pause | "Live weather is wet — skip exposed walking." | `:747` |
| Stay-home music | "Relaxing background music for a cozy night in." | `:715` |
| Stay-home streaming | "Watch at home — no need to go out. Streaming for free on your existing subscriptions." | `:702` |
| Bare buffer (first) | "Buffer time so the evening feels unhurried and matches your time budget." | `:1495` (from `_best_filler`) |

Restaurant is only *partially* templated now: the blurb varies by cuisine
note and gets a separate food-priority wording (`orchestrator.py:756-760`),
but it still never names the venue.

The **LLM plan prompt** (`PLAN_PROMPT`) has the same risk — it is a template
(`orchestrator.py:416`) and if the planner returns an empty step list the app
silently substitutes the heuristic plan (`orchestrator.py:2306-2308`), so
verbatim strings above can appear even when a movie/cafe did exist.

## What's already contextual

This is a *partial* issue: several blurbs ARE venue/order-aware:
- Café blurb uses `_venue_descriptor` (`orchestrator.py:1277`) — dessert spot
  vs quick snack vs sit-down restaurant vs café (`:790`).
- `_best_filler` second-activity `why`
  (`orchestrator.py:1472-1475`) — named venue + nearest-yet-mood phrasing.
- `_music_why` (`orchestrator.py:1305`) — references actual preceding step
  (film/meal/evening) + music language.
- `_finalize_step_order_and_blurbs` (`orchestrator.py:1694`) regenerates
  position-dependent blurbs.
- `_fix_generic_place_names` (`orchestrator.py:1724`) swaps LLM-invented
  generic place titles for real ranked candidates.
- Extra pacing buffers get distinct copy from `_BUFFER_VARIANTS`
  (`orchestrator.py:1502-1515`), so only the *first* bare buffer is generic.

## Suggested fix (not yet implemented)

- Pull the picker's real chosen venue (from `_pick_dining` result, not just
  `restaurant["title"]`) into the `why` text for the remaining template cases:
  walk, rainy pause, stay-home music/streaming.
- Replace "after college" phrasing for non-student inputs (it's a leftover of
  the demo persona).

## Connects to

- [[Plan Assembly]] · [[Budget Fit Duration]]
- [[Frontend]]

## Used by

- [[00-Home]]