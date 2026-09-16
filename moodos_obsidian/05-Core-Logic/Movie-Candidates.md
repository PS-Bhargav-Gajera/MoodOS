---
tags: [moodos, core-logic, movies]
---

# Movie Candidates

How an "in theaters" movie showing is synthesized from real cinemas + canned
showtimes.

## Source

`_movie_candidates(cinemas, lat, lon)` (`orchestrator.py:75`).

- Takes the Overpass cinema venues ([[Find Nearby Cinemas]]) and, for every
  venue, attaches a canned show from the `CINEMA_SHOWS` mock pool
  ([[Mock cinema shows]], `actions.py:7`) — each entry has a `movie`, `time`,
  `price_inr`, `seats`.
- Pairs one real cinema with one canned show title → a `kind: movie`,
  `has_venue: true` candidate with `venue`, `showtime` disclaimer, distance.

Then [[Movie Metadata and Mood Fit]] resolves the REAL runtime/genre by title
via TMDB (or marks it `(est.)`). Showtimes themselves are **mock** — the plan
explicitly labels showtime as estimated/disclaimer (`orchestrator.py:553-555`).

## Fidelity notes

- Runtime without a TMDB key/success → pool default (130/140) + `is_estimate`.
- `_pick_best_movie` (`orchestrator.py:284`) picks among these using genre/mood
  fit ([[Movie Metadata and Mood Fit]]).
- Tested indirectly: `test_location_aware_showtimes_nearest_first`
  (`tests/test_pipeline.py:38`) asserts ≥2 shows with coords after `list_showtimes`.

## Connects to

- [[Find Nearby Cinemas]] · [[Mock cinema shows]] · [[Movie Metadata and Mood Fit]]
- [[Tmdb Disambiguation]] (same-title risk)

## Used by

- `run_pipeline` (`orchestrator.py:1311`) · [[Movie Metadata and Mood Fit]]