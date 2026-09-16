---
tags: [moodos, data-source, provider]
---

# iTunes Search

Free iTunes Search API — the music **fallback** when Spotify search fails/setup
missing.

## Source

`providers.search_music` (`providers.py:649`) iTunes branch
(`https://itunes.apple.com/search`).

## How seed/refresh works here

iTunes has **no offset**, so the provider:
1. fetches a pool of `min(200, (seed+1)*limit)` rows,
2. slices the `[seed*limit : seed*limit+limit]` window
   (`providers.py:663, 676`).

Real durations come from `trackTimeMillis` (`duration_min` rounded,
`duration_sec` floored). Items carry `source: "itunes-search"`, `preview_url`
and a `collectionName`/genre text.

Media request uses `country=IN` by default; market is derived from the user's
location in the pipeline (`slots["music_region"]`, `orchestrator.py:1252-1253`,
`1283`).

## Connects to

- [[Search Music]] · [[Spotify]] · [[TTL Cache]] (6 h)

## Used by

- [[Create Playlist]] · [[Route Playlist Prepare]]