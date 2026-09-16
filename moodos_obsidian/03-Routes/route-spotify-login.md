---
tags: [moodos, route, api]
---

# Route Spotify Login

`GET /spotify/login` → `app.py:145`

## Behavior

- 400 if Spotify is not configured.
- Redirects to `spotify_api.authorize_url()` (`spotify.py:120`): Spotify
  authorize URL with `playlist-modify-private`, `playlist-modify-public`,
  `user-read-email` scopes and a random `state`. State is kept in memory
  (`_oauth_state`) and validated on callback.

Linked from the nav "Connect Spotify" button (`index.html:25`).

## Connects to

- [[Spotify]] · [[Spotify 403 Premium]]

## Used by

- [[Frontend]]