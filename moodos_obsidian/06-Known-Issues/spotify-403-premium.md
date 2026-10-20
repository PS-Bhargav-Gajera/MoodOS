---
tags: [moodos, known-issue, bug, spotify]
---

# Spotify 403 on Playlist Creation

> **Rewritten.** The previous version of this note claimed the failure was
> "403 Active premium subscription required for the owner of the app". That
> diagnosis was wrong on all three of its claims and sent the fix in the wrong
> direction. What follows is the verified version.

## Symptom

The playlist panel showed the internal code **`create_failed`** instead of a
sentence. The user had already connected Spotify and was told to connect it
again, with no indication that reconnecting could not help.

## Verified cause: a stale OAuth grant, not Premium

Probed live against the connected account on 2026-09-29:

| Probe | Scope involved | Result |
| --- | --- | --- |
| `GET /v1/me` | — | `200`, `product: "premium"` |
| `GET /v1/search` (user token) | — | `200` |
| `GET /v1/search` (app token) | — | `200` |
| `GET /v1/me/top/artists` | `user-top-read` (in `SCOPES`) | `200` |
| `GET /v1/me/playlists` | `playlist-read-private` (**not** in `SCOPES`) | `403 "Insufficient client scope"` |
| `POST /v1/users/{id}/playlists` | `playlist-modify-private` (in `SCOPES`) | `403 "Forbidden"`, no `reason` |

The account is Premium and search works on both credentials, so the
client-credentials 403 this note used to describe does not reproduce.

The stored refresh token was granted **before** the `playlist-*` scopes were
added to `SCOPES`. The read probe proves the grant is missing that scope
family independently, and Spotify names scope problems explicitly when it
chooses to. `GET /v1/me/top/artists` returning `200` rules out a blanket
Development Mode block: user-context access works.

**OAuth scopes are immutable per grant.** Refreshing a token can never widen
it — only a fresh re-consent at [[Route Spotify Login]] can. No amount of
retrying recovers from this.

## What made it invisible

`spotify.create_playlist` returned `create_failed` on any `>= 400` while
discarding both the status code and the response body, so nothing ever reached
`server.err.log` and there was nothing to diagnose. `user_connected()` only
checked that a token file existed, so a token that could never create a
playlist still reported as connected.

## Fix (implemented)

- `spotify._token_record` stores the `scope` Spotify actually granted
  alongside the token, so this is self-diagnosing from now on.
- `spotify.scope_gap()` / `can_create_playlists()` compare that grant against
  `CREATE_SCOPES`. `create_playlist` short-circuits before calling Spotify when
  the grant is too narrow — it cannot succeed, so calling out is wasted.
- Every `status` string is mapped to user-facing copy in
  `spotify.USER_MESSAGES`; `create_failed` is split by HTTP status into
  expired / missing-permission / rate-limited / generic.
- The status, endpoint and Spotify's own reason go to the log
  (`_log_spotify_failure`), including the `/v1/me` `product` field that
  settles Premium questions outright.

## Remedy for the current token

Delete `data/spotify_tokens.json` and reconnect via [[Route Spotify Login]].
The refreshed grant carries the full scope set and creation should succeed.
Until then the panel explains why it is asking again.

## Connects to

- [[Spotify]] · [[Search Music]] · [[Create Playlist]] · [[Route Playlist Confirm]]
- [[Route Spotify Login]]

## Used by

- [[00-Home]] · [[Search Music]]

## Note on the iTunes fallback

The old note described a silent iTunes fallback. That path no longer exists —
`providers.search_music` is documented as deliberately Spotify-only. The
`source: itunes-search` label in old notes and logs is historical.
