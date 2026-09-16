---
tags: [moodos, route, http, static]
---

# Route Root

`GET /` → serves the SPA shell (`static/index.html`)
(`app.py:67-69`). No other route. `STATIC` resolves to the repo's `static/`
folder, so the entire UI (see [[Frontend]] and `static/app.js`) is a single
static page talking to the `/api/*` endpoints below.

## Behavior

- Returns `FileResponse(STATIC / "index.html")` — no templating, no caching
  headers (the browser may cache it).
- All subsequent interaction is XHR/fetch to the API, not page navigation:
  `health()` polls `GET /api/health` on load (`app.js:69-71,599`), then a plan
  is posted to [[Route Plan]].

## Connects to

- [[Frontend]] · [[Route Health]] · [[Route Plan]]

## Used by

- Browser navigation (`http://127.0.0.1:8000/`)