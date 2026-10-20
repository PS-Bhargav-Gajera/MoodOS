---
tags: [moodos, tool, mcp]
---

# Create Playlist

MCP tool `create_playlist` → `MoodOSMCPServer.create_playlist`
(`moodos/mcp_server.py:171`).

## Signature

`create_playlist(query: str, confirm: bool = False, seed: int = 0) -> dict`

## Behavior

1. `providers.search_music(query, seed=seed)` ([[Search Music]], Spotify-only)
   → live tracks with real durations.
2. If **not confirmed** → returns a *prepared* payload
   (`status: prepared`, `requires_confirmation: True`, `query`, `seed`,
   `tracks[:8]`, `spotify_connected` (= `spotify.can_create_playlists()`,
   `spotify.py:326`), `scope_gap` (`spotify.py:313`), `authorize_url`,
   and `provider` = `tracks[0].source`).
3. If **confirmed** → `spotify_api.create_playlist(name, uris, confirm=True)`
   ([[Spotify]], `spotify.py:435`): needs the *user* OAuth token (`needs_auth`
   + `authorize_url` otherwise) and a grant without a scope gap — a stale
   grant short-circuits with `create_failed`/`scope_gap` **without** calling
   Spotify (`spotify.py:445-466`). Playlist name is chosen by keyword
   heuristics (`_playlist_name`, `mcp_server.py:197`).

Supported by two routes: [[Route Playlist Prepare]] (with `seed` for refresh)
and [[Route Playlist Confirm]].

## Connects to

- [[Search Music]] · [[Spotify]]
- [[Route Playlist Prepare]] · [[Route Playlist Confirm]]
- [[Frontend]] (live track panel + refresh)

## Used by

- [[Route Playlist Prepare]]
- [[Route Playlist Confirm]]