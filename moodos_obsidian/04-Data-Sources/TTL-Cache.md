---
tags: [moodos, data-source, storage, cache]
---

# TTL Cache

Short-lived dynamic cache persisted to `data/ttl_cache.json`
(`settings.cache_path`, `config.py:62`; `moodos/cache.py`).

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
| Weather | `weather:{lat}:{lon}` (rounded) | 15 min (`providers.py:55`) |
| Reverse geocode | `rev:{lat}:{lon}` | 6 h (`providers.py:134`) |
| Places (Overpass/Nominatim) | `places:{lat}:{lon}:{q}` | 20 min (`providers.py:160`) |
| Walks | `walks:{lat}:{lon}`, `walkspot:...` | 30 min |
| Nearby POIs / cinemas | `poi:{lat}:{lon}:{radius}:{cats}:{limit}` | 30 min, 3 min when empty (`location_service.py:247`) |
| Restaurants | `restaurants:{lat}:{lon}:{cuisine/dietary...}:{radius}` | 20 min (`providers.py:643`) |
| Music | `music:{query}\|{country}\|seed={seed}` | 20 min (`providers.py:854`) |
| Books | `books:{query}` | 6 h (`providers.py:834`) |
| TMDB search/discover/now-playing | `tmdb:...`, `tmdb-disc:...`, `tmdb-now:...` | 3-6 h |
| TMDB details/metadata | `tmdb-detail:...`, `tmdb-meta:...` | 24 h |
| TMDB watch/trending/recs | `tmdb-watch:...`, `tmdb-trending:...`, `tmdb-rec:...` | 6-12 h |
| Web snippets | `web:{query}` | 2 h (`providers.py:1350`) |

Because `seed` is part of the music key, **refreshing with a new seed bypasses
the cache** and returns fresh songs (see [[Search Music]]).

## Connects to

- Every provider in 04-Data-Sources
- [[Persistence]]

## Used by

- [[Architecture-Overview]]