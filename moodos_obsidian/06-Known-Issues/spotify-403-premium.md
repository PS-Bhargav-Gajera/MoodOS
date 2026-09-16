---
tags: [moodos, known-issue, bug, spotify]
---

# Spotify 403 Premium

**Observed (server.err.log)**: live Spotify search returns
`403 Active premium subscription required for the owner of the app.`

## What it means

Since Spotify's policy change, `GET /v1/search` with a **client-credentials**
(app) token returns 403 unless the **app-owner account has Spotify Premium**.
The user has provided `SPOTIFY_CLIENT_ID/SECRET`, but search silently fails.

## Current behavior (verified)

- `spotify.search_tracks` (`spotify.py:62`) catches the >=400 response and
  returns `[]` (logs a warning).
- `providers.search_music` (`providers.py:656-659`): no Spotify tracks →
  **iTunes fallback** ([[iTunes Search]]) — the plan/playlist still works, now
  labeled `source: itunes-search`.
- The UI shows this state honestly: the playlist panel displays a provider note
  ("via itunes-search — Spotify search unavailable (needs Premium…)") and the
  `provider` field returned by [[Create Playlist]].

## Impact

- Yes: music is served by iTunes (search) and the playlist *requires* the user
  OAuth connect to actually be created on Spotify ([[Route Playlist Confirm]]).
- No: warnings before every refill; users can't verify via search results
  whether iTunes ≠ Spotify quality for regional/Hindi queries
  (iTunes pool is `country=IN`).

## Suggested fix (not yet implemented)

- Upgrade the app-owner Spotify account to Premium (external).
- Or fall back to user-token search for search when the app token 403s
  (only possible after the user connects via [[Route Spotify Login]]).

## Connects to

- [[Spotify]] · [[Search Music]] · [[Create Playlist]] · [[iTunes Search]]
- [[Route Spotify Login]] · [[Route Playlist Prepare]]

## Used by

- [[00-Home]] · [[Search Music]]