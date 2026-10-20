---
tags: [moodos, core-logic, movies, metadata]
---

# Movie Metadata and Mood Fit

Resolving real runtime/genre for a movie title and checking it fits a calm /
relaxed target. (If not verified → honest `(est.)` + disclaimer.)

## Runtime/genre resolution (`providers.py`)

- `movie_metadata_by_title(title, hint_year, hint_language)`
  (`providers.py:1109`): searches TMDB, `_disambiguate_movie`
  (`providers.py:868`) picks an exact-title-match candidate with a runtime/year
  (and year/language hints boost or penalize), `_disambiguation_confident`
  (`providers.py:933`) gates it. No key / no pass → explicitly
  `source: estimate`, `genre_source: unknown` — never a fabricated runtime.
- `movie_runtime_by_title` (`providers.py:1158`) — thin wrapper used by
  [[Plan Assembly]] step pinning inside `_normalize_movie_steps`
  (`orchestrator.py:1207`).

## Mood fit (`providers.py:1175-1210`)

- `_RELAX_GOOD_GENRES` (comedy/animation/family/romance/music/documentary/
  fantasy/adventure...) vs `_RELAX_POOR_GENRES` (thriller/horror/war/crime/
  mystery/action/noir).
- `_INTENSE_KEYWORDS` scan the overview/tagline (disturbing, trauma, suicide,
  murder, violence, suspense...).
- `classify_movie_fit(genres, overview, tagline)` (`providers.py:1190`) →
  `("good"|"neutral"|"poor", reason)`. Drama is judged from the text.

## Where it lands

- `genre_fit` / `genre_fit_reason` / `mood_fit_verified` are **computed** in
  `_movie_candidates` (`orchestrator.py:278-306`): verified only when TMDB
  returned real genres (`mood_fit_verified = bool(genres)`, `:306`).
- `_pick_best_movie` (`orchestrator.py:535`) + `_movie_blurb`
  (`orchestrator.py:583`) **consume** them to choose the film and write the
  movie step `why`: on a relax target, unverified (`unknown`) and `poor`
  films are excluded unless the user explicitly asked for a movie.
- `_normalize_movie_steps` (`orchestrator.py:1178`) pins `duration_min` from
  the real runtime and copies `genre_fit`/`mood_fit_verified` onto the step
  (`:1231-1232`), setting `flexible: false`.
- `_movie_request_note` (`orchestrator.py:1158`) adds "couldn't verify tone"
  disclaimers.

## Known issue

Same-titled films can pick the wrong TMDB record (wrong runtime/genre) — the
tie-break is popularity/votes when year & language hints are absent. See
[[Tmdb Disambiguation]].

## Connects to

- [[TMDB]] · [[Tmdb Movie Details]] · [[Movie Candidates]] · [[Plan Assembly]]
- [[Hard Filtering and Constraints]]

## Used by

- [[Request Flow]] · [[Home vs Out Mode]]