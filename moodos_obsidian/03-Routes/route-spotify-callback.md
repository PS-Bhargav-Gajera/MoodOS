---
tags: [moodos, route, api]
---

# Route Spotify Callback

`GET /spotify/callback` → `app.py:152`

## Behavior

- Errors from Spotify (denied) → 400.
- `spotify_api.exchange_code(code, state)` (`spotify.py:134`) — validates the
  in-memory `state`, POSTs to the token endpoint, stores
  `access_token`/`refresh_token`/`expires` in `data/spotify_tokens.json`
  ([[Spotify]]). Invalid/missing state or exchange failure → 400.
- Redirects back to `/` on success.

Redirect URI configured in `.env.example`:
`http://127.0.0.1:8000/spotify/callback`.

## Connects to

- [[Spotify]] · [[Persistence]]

## Used by

- External OAuth flow from [[Route Spotify Login]]