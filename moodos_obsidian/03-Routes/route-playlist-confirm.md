---
tags: [moodos, route, api]
---

# Route Playlist Confirm

`POST /api/playlist/confirm` → `app.py:167`

## Request

```json
{ "query": "calm acoustic evening", "confirmed": true }
```

## Behavior

`mcp.call("create_playlist", query=query, confirm=confirmed)`. With
`confirmed=true` this executes the real **Spotify playlist creation**
(`spotify.py:201`): requires the user OAuth token (returns `needs_auth` +
`authorize_url` otherwise), creates a private playlist, then adds the track
URIs (`uris[:50]`). Returns `playlist_url` + `provider: Spotify` on success.

Frontend: "Create playlist" button is disabled after one confirm
(`app.js:506-518`).

## Connects to

- [[Create Playlist]] · [[Spotify]]

## Used by

- [[Frontend]] · [[00-Home]]