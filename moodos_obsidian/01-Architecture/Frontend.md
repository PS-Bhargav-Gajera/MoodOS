---
tags: [moodos, architecture, frontend]
---

# Frontend

Vanilla JS + CSS, no build step. `static/index.html` (`index.html:1-62`) loads
`static/app.js` and `static/styles.css`.

## Page skeleton

- Nav: agent status chips (`#keys`), Connect Spotify link (`/spotify/login`) —
  `index.html:24-25`, wired by `health()` (`app.js:69-79`).
- Location bar (`#here`) — live GPS, IP, or typed city text
  (`app.js:5-17`, `requestGeo` `app.js:19-65`).
- Textarea `#msg` prefilled with a realistic mood+budget+time prompt,
  `#loc` city field, `#prompt` workflow select, `#go` send button
  (`index.html:35-54`).
- `#status` + `#result` panels.

## HTTP calls it makes

| Call | Context | Note |
|---|---|---|
| `GET /api/health` | boot chips | `app.js:71` |
| `GET https://api.ipify.org` | public IP for location | `app.js:89` |
| `POST /api/location/resolve` | geo + typed city | `app.js:102`, debounced on input (`app.js:601`) |
| `POST /api/plan` | main ask | `app.js:573` |
| `POST /api/feedback` | like/dislike buttons | `app.js:433` |
| `POST /api/booking/prepare` | movie booking preview | `app.js:448` |
| `POST /api/booking/confirm` | user confirms booking | `app.js:455` |
| `POST /api/playlist/prepare?query&seed` | prepare playlist | `app.js:470` |
| `POST /api/playlist/confirm` | create Spotify playlist | `app.js:508` |
| `GET /api/restaurants?...` | "Find restaurants" button | `app.js:531` — different path from the plan, see [[Find Restaurants button path]] |

## Rendering (`render(data)`, `app.js:360-546`)

- Meta rows for slots (mood/current/desired), weather, location resolver audit
  (`app.js:374-423`).
- **Stay-home**: streaming movies grid; **going out**: restaurant cards +
  "Find restaurants" button (`app.js:421-427`).
- Plan steps with travel legs, per-stop duration/cost, movie runtime +
  showtime disclaimer, music step with a real track list
  (`renderStep`, and `renderPlaylistPanel` for the live panel).
- Movie booking flow: prepare → show price/showtime as "No money charged until
  you confirm" → confirm (`app.js:444-466`).
- Playlist flow: prepare with seed → live track rows (`m:ss` per song, total
  `N songs · X min`) → refresh suggestions (`#plrefresh`), Spotify-connect hint,
  provider note — `renderPlaylistPanel` (`app.js:480-522`); confirm disables after trigger.
- Feedback buttons and friendly "Oops" on any fetch failure (`app.js:583-593`).

## Connects to

- [[Route Root]] · [[Route Plan]] · [[Route Location Resolve]] · [[Route Health]] · [[Route Restaurants]] · [[Route Playlist Prepare]] · [[Route Playlist Confirm]] · [[Route Booking Prepare]] · [[Route Booking Confirm]] · [[Route Feedback]] · [[Route Spotify Login]]
- [[Search Music]] · [[Create Playlist]]

## Used by

- [[00-Home]]
- [[Architecture-Overview]]