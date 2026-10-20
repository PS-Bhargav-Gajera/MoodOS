---
tags: [moodos, core-logic, movies]
---

# Movie Candidates

How an "in theaters" movie showing is synthesized from real cinemas + estimated
showtimes (live TMDB titles).

## Source

`_movie_candidates(cinemas, lat, lon, region="IN", films=None)`
(`orchestrator.py:247`).

- Takes the Overpass cinema venues ([[Find Nearby Cinemas]]) and, for every
  venue, attaches a show built by `actions.list_showtimes`
  ([[Mock cinema shows]], `actions.py:13` — TMDB now-playing titles paired with
  estimated times; show `i` goes to venue `i`, `orchestrator.py:263-266`) —
  each entry has a `movie`, `time`, `price_inr`, `seats`.
- Pairs one real cinema with one show title → a `kind: movie`,
  `has_venue: true` candidate with `venue`, `showtime_disclaimer`, distance
  (`orchestrator.py:282-315`).

Then [[Movie Metadata and Mood Fit]] resolves the REAL runtime/genre by title
via TMDB (or marks it `(est.)`; `runtime_source: "estimate"`,
`is_estimate`). Showtimes themselves are **estimated** — the plan copies the
disclaimer onto steps (`orchestrator.py:1226-1227`).

## Fidelity notes

- Runtime without a TMDB key/success → 130 min default + `is_estimate`
  (`orchestrator.py:290`, `293`); cinema venues themselves default to 140 min
  (`providers.py:388`).
- `_pick_best_movie` (`orchestrator.py:535`) picks among these using genre/mood
  fit ([[Movie Metadata and Mood Fit]]).
- Tested indirectly: `test_location_aware_showtimes_nearest_first`
  (`tests/test_pipeline.py:42`) asserts ≥2 shows with coords after
  `list_showtimes`.

## Connects to

- [[Find Nearby Cinemas]] · [[Mock cinema shows]] · [[Movie Metadata and Mood Fit]]
- [[Tmdb Disambiguation]] (same-title risk)

## Used by

- `run_pipeline` (`orchestrator.py:2028`; call site `orchestrator.py:2217`) · [[Movie Metadata and Mood Fit]]