---
tags: [moodos, tool, mcp]
---

# Prepare Movie Booking

MCP tool `prepare_movie_booking` → `lambda i=0: actions.prepare_movie_booking(i)`
(`moodos/mcp_server.py:36`).

## Signature

`prepare_movie_booking(show_index: int = 0) -> dict`

## Behavior

`actions.prepare_movie_booking` (`actions.py:54`) — **no real PVR/BookMyShow
API is ever called**. It resolves a show object from `list_showtimes`
(`actions.py:13`), which pairs live TMDB now-playing titles with *estimated*
evening times — the canned cycle `_EST_TIMES` ("17:50", "18:40", "19:15",
"20:00", "21:10") and `_EST_PRICES` (₹220/230/250/260/240), every show marked
`showtime_estimated: True` with `cinema: None` (real OSM venue names are
attached later by `_movie_candidates`, `orchestrator.py:263-296`). Default is
4 seeded shows; times/prices cycle by index.

Selecting: with a non-empty show list the first branch (`actions.py:55`) always
resolves to `shows[0]` — `min(show_index, 0)` pins it to index 0 (pinned by
`tests/test_routes.py:282`); `show_index` only rotates which show is used when
that list is empty (`actions.py:58`, `show_index % len(shows)`).

Payload: `status: prepared`, `requires_confirmation: True`, the `show` object,
`expires_at` = now + 8 minutes, and an explicit note that **no money is
charged** and the showtime must be confirmed at the cinema — "This is not a
live ticket purchase."

Called by `POST /api/booking/prepare` (`app.py:320-322`, [[Route Booking
Prepare]]), invoked from the frontend "Prepare movie booking" button
(`static/app.js:496`, fetch at `:536`).

## Connects to

- [[Mock cinema shows]] · [[Movie Candidates]]
- [[Route Booking Prepare]]

## Used by

- [[Route Booking Prepare]]
- Public MCP surface
