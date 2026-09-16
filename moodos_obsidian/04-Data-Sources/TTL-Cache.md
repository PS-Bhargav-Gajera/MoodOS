---
tags: [moodos, data-source, storage, cache]
---

# TTL Cache

Short-lived dynamic cache persisted to `data/ttl_cache.json`
(`moodos/cache.py`).

## Source

`TTLCache` (`cache.py:16`):
- `get(key)` drops expired items (and re-saves the file) under a lock; returns
  `None` on miss.
- `set(key, value, ttl_seconds)` rewrites the full JSON file on every write.

A global instance `ttl_cache` is shared app-wide. **Do not permanently embed
live facts** (file docstring) — it's for provider responses only.

## Key shapes

| Cache | Key | TTL |
|---|---|---|
| Weather | `weather:{lat}:{lon}` (default) | minutes |
| Places / walks | `places:{lat}:{lon}:{q}`, `walks:...` | 20 min |
| Cinemas | `cinemas:{lat}:{lon}` | 24 h |
| Restaurants | `restaurants:{lat}:{lon}:{cuisine/dietary...}:{radius}` | ~1 h |
| Music | `music:{query}|{country}|seed={seed}` | 6 h |
| Books | `books:{query}` | 6 h |
| TMDB search/metadata | `tmdb:...`, `tmdb-meta:...`, `tmdb-detail:...` | 6-24 h |
| TMDB watch/trending/recs | `tmdb-watch:...` etc. | 6-12 h |
| Web snippets | `web:{query}` | 2 h |

Because `seed` is part of the music key, **refreshing with a new seed bypasses
the cache** and returns fresh songs (see [[Search Music]]).

## Connects to

- Every provider in 04-Data-Sources
- [[Persistence]]

## Used by

- [[Architecture-Overview]]