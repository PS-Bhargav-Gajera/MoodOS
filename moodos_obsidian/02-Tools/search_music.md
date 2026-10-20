---
tags: [moodos, tool, mcp]
---

# Search Music

MCP tool `search_music` → `lambda q, country="IN", limit=5: providers.search_music(q, country=country, limit=limit)`
(`moodos/mcp_server.py:26`).

## Signature

`search_music(query: str, limit: int = 5, country: str = "IN", seed: int = 0) -> list`

## Behavior

`providers.search_music` (`providers.py:840`) is **Spotify-only** — there is
deliberately **no iTunes (or any other) fallback**:

1. Delegates to `spotify.search_tracks` ([[Spotify]], `spotify.py:252`) with
   `offset = seed * limit`, trying the connected user token first, then the
   app client-credentials token.
2. Failure (no key, 403, network error) → an honest **empty list**
   (`spotify.py:280-283`) — an invented catalogue entry is worse than showing
   nothing (`providers.py:841-846`).
3. Cache key `music:{query}|{country}|seed={seed}` — the seed is part of the
   key, so refreshing with a new seed returns genuinely new songs; TTL 20 min
   (`providers.py:854`, [[TTL Cache]]).

Every track carries real `duration_min`/`duration_sec` (from `duration_ms`)
plus `source: spotify` (`spotify.py:196-213`).

## Connects to

- [[Spotify]] · [[TTL Cache]]
- [[Create Playlist]]

## Used by

- `run_pipeline` parallel tasks (`orchestrator.py:2190`)
- [[Create Playlist]] (via `mcp.create_playlist`)
- [[Route Playlist Prepare]]

## Known issue

See [[Spotify 403 Premium]] — when search fails the music leg is flagged
honestly as unavailable (`orchestrator.py:1330-1337`,
`tracks_source: "spotify (no match)"`), never backfilled from another
catalogue.
