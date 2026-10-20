---
tags: [moodos, data-source, provider]
---

# TMDB

The Movie Database — movie search, real runtimes, genres, trending and watch
providers. Free API key (`TMDB_API_KEY`).

## Functions

- `search_movies_tmdb` (`providers.py:979`) — `/search/movie`, per-title runtime
  via details; used by [[Search Movies]] and [[Search Home Movies]].
- `tmdb_movie_details` (`providers.py:1072`) / `_tmdb_runtime_min`
  (`providers.py:1102`) — runtime + genres ([[Tmdb Movie Details]]).
- `tmdb_watch_providers` (`providers.py:1238`) — region OTT availability
  ([[Tmdb Watch Providers]]).
- `tmdb_trending` (`providers.py:1268`) · `tmdb_recommendations`
  (`providers.py:1299`) · `tmdb_now_playing` (`providers.py:1017`).
- The "real movie metadata by title" stack: `_disambiguate_movie`
  (`providers.py:868`), `_disambiguation_confident` (`providers.py:933`),
  `movie_metadata_by_title` (`providers.py:1109`),
  `movie_runtime_by_title` (`providers.py:1158`) → [[Movie Metadata and Mood Fit]].

## Important nuances

- **No key → empty lists**; metadata functions return explicit
  `estimate`/`unknown` results instead of fabricated runtimes
  (`providers.py:1124-1128`, `1145-1151`).
- Runtime default when TMDB is missing: pool/estimate (130/140/120) and every
  step is flagged `is_estimate` + `runtime_source: estimate`.
- Trend/rec entries hardcode 120/130 min (`providers.py:1288`, `1318`) even
  though they're "watch at home".

## Caching

24 h for details/metadata; 12 h for watch providers/recommendations; 3-6 h for
searches/now-playing/discover/trending (see [[TTL Cache]]).

## Known issue

Same-title films can be resolved to the wrong film (wrong runtime/genre) —
see [[Tmdb Disambiguation]] in 06-Known-Issues.

## Connects to

- [[Search Movies]] · [[Search Home Movies]] · [[Tmdb Movie Details]] · [[Tmdb Watch Providers]] · [[Tmdb Trending]] · [[Tmdb Recommendations]]
- [[Movie Metadata and Mood Fit]] · [[Movie Candidates]]

## Used by

- [[Request Flow]] · [[Architecture-Overview]]