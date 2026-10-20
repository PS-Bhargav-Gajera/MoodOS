---
tags: [moodos, known-issue, bug, tmdb]
---

# Tmdb Disambiguation

**Reported**: TMDB title disambiguation sometimes returns the wrong runtime /
genre for a correct movie pick.

## What happens

A movie like "The Lunchbox (2013)" may be resolved to another film sharing the
same title (e.g. a different-language same-title film), so the plan pins a
**wrong runtime as a FIXED duration** (`_normalize_movie_steps`,
`orchestrator.py:1212-1222`) and wrong
genres/tone get used for the mood-fit blurb. When disambiguation correctly
fails, the fallback marks the runtime as `(est.)` — but when it silently picks
the wrong film, the data looks real.

## Root cause (verified in code)

`_disambiguate_movie` (`providers.py:868`):

1. Only exact-title matches count (`mt != q: continue`, `providers.py:896`) —
   good, but two films with the **same title** both pass.
2. Scoring (`providers.py:898-924`): `+1` having a runtime, `+0.5` tmdb id,
   `+0.4` year, then year/language *hints* if provided (year ±`+2.0`/`-1.0`,
   language `+1.0`/`-1.0`), then popularity/votes
   bonus `0.1*min(pop/100,1)+0.1*min(votes/1000,1)`.
3. **When `hint_year`/`hint_language` are absent** the "well-known release
   wins" rule is just popularity + votes. No caller ever supplies hints: the
   plan's runtime fallback calls `providers.movie_runtime_by_title(title)`
   with none (`orchestrator.py:1207`), and [[Movie Candidates]] resolves
   runtimes through `tmdb_movie_details(tmdb_id)` rather than title
   (`orchestrator.py:247-317`). Remakes/reboots and same-name regional films
   therefore lose to a more popular same-title entry.
4. `_disambiguation_confident` (`providers.py:933`) only checks `tmdb_id` +
   (runtime OR release_date) — it does **not** re-verify the choice is the
   *right film*.

Secondary path: `_normalize_movie_steps` (`orchestrator.py:1178`) does substring
matching (`title in tlow or tlow in title`, `:1195-1198`) and can cross-match
"Paddington in Peru" to a substring hit, then pins its runtime.

## Impact

- Step `duration_min` becomes the wrong film's runtime and is **flexible=False**
  (locked by [[Budget Fit Duration]]), distorting the total.
- `genre_fit`/`mood_fit_verified` may describe the wrong film.

## Suggested fix (not yet implemented)

- Prefer `original_title` + year equality over popularity when ties involve
  distinct `release_date` years.
- Carry `hint_year`/`hint_language` into `movie_metadata_by_title` from the
  cinema show metadata (currently absent).
- Gate by a popularity/vote floor so an unknown same-name film can't win.

## Connects to

- [[Movie Metadata and Mood Fit]] · [[Movie Candidates]] · [[TMDB]]
- [[Budget Fit Duration]]

## Used by

- [[00-Home]]