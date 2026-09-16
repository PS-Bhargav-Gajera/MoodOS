---
tags: [moodos, tool, mcp]
---

# Search Music

MCP tool `search_music` → `lambda q, country="IN": providers.search_music(q, country=country)`
(`moodos/mcp_server.py:24`).

## Signature

`search_music(query: str, limit: int = 5, country: str = "IN", seed: int = 0) -> list`

## Behavior

`providers.search_music` (`providers.py:649`):

1. Try **Spotify** search first with `offset = seed * limit`
   ([[Spotify]], `spotify.py:62`).
2. If Spotify returns nothing (e.g. 403 Premium — see [[Spotify 403 Premium]]),
   fall back to **iTunes Search** ([[iTunes Search]]).
   iTunes has no offset, so a pool of up to 200 results is fetched and a
   `seed`-window is sliced (`providers.py:663, 676`).
3. Cache key `music:{query}|{country}|seed={seed}` — the seed is part of the
   key, so refreshing with a new seed returns genuinely new songs
   ([[TTL Cache]]).

Every track carries real `duration_min`/`duration_sec` (from
`duration_ms`/`trackTimeMillis`) plus `source` (`spotify` | `itunes-search`).

## Connects to

- [[Spotify]] · [[iTunes Search]] · [[TTL Cache]]
- [[Create Playlist]]

## Used by

- `run_pipeline` parallel tasks (`orchestrator.py:1283`)
- [[Create Playlist]] (via `mcp.create_playlist`)
- [[Route Playlist Prepare]]

## Known issue

See [[Spotify 403 Premium]] — search degrades to iTunes when the owning app
account has no Premium.