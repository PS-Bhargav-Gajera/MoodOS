---
tags: [moodos, data-source, provider]
---

# Spotify

Spotify Web API — two credential modes.

Music is **Spotify-only** — there is deliberately no iTunes/seed fallback
(`providers.search_music`, `providers.py:840-846`): on error it returns an
honest empty list rather than a fabricated catalogue entry.

## App credentials (`SPOTIFY_CLIENT_ID/SECRET`)

- Client-credentials token: `app_access_token` (`spotify.py:156`), cached in
  memory.
- **Track search**: `search_tracks(query, limit=8, market="IN", offset=0)`
  (`spotify.py:252`) — `GET /v1/search`; items carry real
  `duration_min`/`duration_sec` (from `duration_ms`), `preview_url`, `uri`.
  This is what [[Search Music]] tries first; `providers.search_music`
  (`providers.py:840`) delegates to it. On any error it returns `[]`.

## User OAuth (playlist creation)

- Scopes: `playlist-modify-private playlist-modify-public user-read-email
  user-read-private user-top-read` (`spotify.py:20-23`); the playlist-write
  subset is `CREATE_SCOPES` (`spotify.py:26`).
- Token file `data/spotify_tokens.json` (`spotify.py:19`); `authorize_url`
  (`spotify.py:336`) → `accounts.spotify.com/authorize` with
  `redirect_uri` from config `SPOTIFY_REDIRECT_URI` (`config.py:23`) →
  `/spotify/login`; `exchange_code` (`spotify.py:350`) posts
  `grant_type=authorization_code` to `accounts.spotify.com/api/token` →
  `/spotify/callback`.
- Refresh: `_user_access_token` (`spotify.py:396`) uses
  `grant_type=refresh_token`; scope gap checks `scope_gap` (`spotify.py:313`)
  / `can_create_playlists` (`spotify.py:326`).
- `create_playlist` (`spotify.py:435`) → private playlist + `uris[:50]` via
  [[Create Playlist]]. Only runs after explicit `confirm=true`.

## Known constraint

**Search requires the app-owner account to hold Spotify Premium** — otherwise
`GET /v1/search` returns:
`403 Active premium subscription required for the owner of the app.`
`search_tracks` tries the next token and, if all fail, returns an empty list —
see [[Spotify 403 Premium]] and [[Search Music]].

## Connects to

- [[Search Music]] · [[Create Playlist]]
- [[Route Spotify Login]] · [[Route Spotify Callback]] · [[Route Playlist Prepare]] · [[Route Playlist Confirm]]
- [[Persistence]] (token file)

## Used by

- [[Request Flow]] · [[Architecture-Overview]]