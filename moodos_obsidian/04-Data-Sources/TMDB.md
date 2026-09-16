---
tags: [moodos, data-source, provider]
---

# TMDB

The Movie Database — movie search, real runtimes, genres, trending and watch
providers. Free API key (`TMDB_API_KEY`).

## Functions

- `search_movies_tmdb` (`providers.py:789`) — `/search/movie`, per-title runtime
  via details; used by [[Search Movies]] and [[Search Home Movies]].
- `tmdb_movie_details` (`providers.py:839`) / `_tmdb_runtime_min`
  (`providers.py:875`) — runtime + genres ([[Tmdb Movie Details]]).
- `tmdb_watch_providers` (`providers.py:985`) — region OTT availability
  ([[Tmdb Watch Providers]]).
- `tmdb_trending` (`providers.py:1019`) · `tmdb_recommendations`
  (`providers.py:1055`).
- The "real movie metadata by title" stack: `_disambiguate_movie`
  (`providers.py:708`), `_disambiguation_confident` (`providers.py:773`),
  `movie_metadata_by_title` (`providers.py:882`),
  `movie_runtime_by_title` (`providers.py:930`) → [[Movie Metadata and Mood Fit]].

## Important nuances

- **No key → empty lists**; metadata functions return explicit
  `estimate`/`unknown` results instead of fabricated runtimes
  (`providers.py:897-901`).
- Runtime default when TMDB is missing: pool/estimate (130/140/120) and every
  step is flagged `is_estimate` + `runtime_source: estimate`.
- Trend/rec entries hardcode 120/130 min even though they're "watch at home".

## Caching

24 h for details/metadata/watch/location-level data; 6 h for searches/trending
(see [[TTL Cache]]).

## Known issue

Same-title films can be resolved to the wrong film (wrong runtime/genre) —
see [[Tmdb Disambiguation]] in 06-Known-Issues.

## Connects to

- [[Search Movies]] · [[Search Home Movies]] · [[Tmdb Movie Details]] · [[Tmdb Watch Providers]] · [[Tmdb Trending]] · [[Tmdb Recommendations]]
- [[Movie Metadata and Mood Fit]] · [[Movie Candidates]]

## Used by

- [[Request Flow]] · [[Architecture-Overview]]