---
tags: [moodos, tool, mcp]
---

# Create Playlist

MCP tool `create_playlist` → `MoodOSMCPServer.create_playlist`
(`moodos/mcp_server.py:152`).

## Signature

`create_playlist(query: str, confirm: bool = False, seed: int = 0) -> dict`

## Behavior

1. `providers.search_music(query, seed=seed)` ([[Search Music]]) →
   live tracks with real durations.
2. If **not confirmed** → returns a *prepared* payload
   (`status: prepared`, `requires_confirmation: True`, `query`, `seed`,
   `tracks[:8]`, `spotify_connected`, `authorize_url`,
   and `provider` = `tracks[0].source`).
3. If **confirmed** → `spotify_api.create_playlist(name, uris, confirm=True)`
   ([[Spotify]], `spotify.py:201`): only runs when the *user* OAuth token is
   set, with `needs_auth` + `authorize_url` otherwise. Playlist name is chosen
   by keyword heuristics (`_playlist_name`, `mcp_server.py:173`).

Supported by two routes: [[Route Playlist Prepare]] (with `seed` for refresh)
and [[Route Playlist Confirm]].

## Connects to

- [[Search Music]] · [[Spotify]] · [[iTunes Search]]
- [[Route Playlist Prepare]] · [[Route Playlist Confirm]]
- [[Frontend]] (live track panel + refresh)

## Used by

- [[Route Playlist Prepare]]
- [[Route Playlist Confirm]]