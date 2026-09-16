---
tags: [moodos, data-source, provider]
---

# Spotify

Spotify Web API — two credential modes.

## App credentials (`SPOTIFY_CLIENT_ID/SECRET`)

- Client-credentials token: `app_access_token` (`spotify.py:35`), cached in
  memory.
- **Track search**: `search_tracks(query, limit=8, market="IN", offset=0)`
  (`spotify.py:62`) — `GET /v1/search`; items carry real
  `duration_min`/`duration_sec` (from `duration_ms`), `preview_url`, `uri`.
  This is what [[Search Music]] tries first.

## User OAuth (playlist creation)

- Scopes: `playlist-modify-private playlist-modify-public user-read-email`
  (`spotify.py:19`).
- `authorize_url` (`spotify.py:120`) → `/spotify/login`;
  `exchange_code` (`spotify.py:134`) → `/spotify/callback`; tokens stored in
  `data/spotify_tokens.json` with refresh (`_user_access_token`, `spotify.py:169`).
- `create_playlist` (`spotify.py:201`) → private playlist + `uris[:50]` via
  [[Create Playlist]]. Only runs after explicit `confirm=true`.

## Known constraint

**Search requires the app-owner account to hold Spotify Premium** — otherwise
`GET /v1/search` returns:
`403 Active premium subscription required for the owner of the app.`
The provider silently degrades to iTunes (see [[Spotify 403 Premium]] and
[[Search Music]]).

## Connects to

- [[Search Music]] · [[Create Playlist]] · [[iTunes Search]]
- [[Route Spotify Login]] · [[Route Spotify Callback]] · [[Route Playlist Prepare]] · [[Route Playlist Confirm]]
- [[Persistence]] (token file)

## Used by

- [[Request Flow]] · [[Architecture-Overview]]