---
tags: [moodos, route, api]
---

# Route Playlist Prepare

`POST /api/playlist/prepare?query=...&seed=N` → `app.py:162`

## Behavior

`mcp.call("create_playlist", query=query, seed=seed, confirm=False)`
([[Create Playlist]]).

Returns:
```json
{
  "status": "prepared", "requires_confirmation": true,
  "query": "...", "seed": 0,
  "tracks": [ ... 8 real songs with duration_min/duration_sec ... ],
  "spotify_connected": false, "authorize_url": "...",
  "provider": "itunes-search | spotify | none"
}
```

The `seed` parameter varies the search offset (Spotify `offset = seed*limit`,
or a windowed slice of the iTunes pool) so **refresh returns different songs
every time** — see [[Search Music]]. The `provider` field lets the UI show why
Spotify isn't used ([[Spotify 403 Premium]]).

Frontend: `renderPlaylistPanel` (`app.js:480-522`) with a "Refresh suggestions"
button that increments `seed` (`app.js:470`).

## Connects to

- [[Create Playlist]] · [[Search Music]] · [[Spotify]] · [[iTunes Search]]

## Used by

- [[Frontend]] · [[00-Home]]