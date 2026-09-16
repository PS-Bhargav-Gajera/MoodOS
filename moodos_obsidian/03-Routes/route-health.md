---
tags: [moodos, route, api]
---

# Route Health

`GET /api/health` → `app.py:72`

## Response

```json
{
  "ok": true,
  "groq": bool, "gemini": bool,
  "mem0": bool, "spotify": bool, "spotify_user": bool,
  "cost": "free-tier / local retrieval"
}
```

Shows agent readiness to the frontend chips (`app.js:71-78`): Groq/Gemini,
Mem0 cloud, Spotify configured + whether a user OAuth token is stored
(`spotify.user_connected`, `spotify.py:116`).

## Connects to

- [[Agent Router]] · [[Mem0]] · [[Spotify]]

## Used by

- [[Frontend]] · [[00-Home]]