---
tags: [moodos, tool, mcp]
---

# Confirm Movie Booking

MCP tool `confirm_movie_booking` → `actions.confirm_movie_booking`
(`moodos/mcp_server.py:37`).

## Signature

`confirm_movie_booking(confirmed: bool, show: dict | None = None) -> dict`

## Behavior

`actions.confirm_movie_booking` (`actions.py:74`): if `confirmed` is falsy →
`{status: aborted, executed: false}`. Otherwise returns
`{status: recorded, executed: true, provider: "MoodOS (no live ticketing —
confirm at the cinema)", show, confirmation_code: "MOODOS-HHMMSS"}` — the code
is the current clock time, `f"MOODOS-{datetime.now().strftime('%H%M%S')}"`
(`actions.py:82`).

The booking is a **mock** — no ticketing API, no payment, no PVR deep link.
The route layer picks the show from `list_showtimes()[show_index % 2]`
(`app.py:327`) and passes it through as `show`.

## Connects to

- [[Mock cinema shows]] · [[Route Booking Confirm]]

## Used by

- [[Route Booking Confirm]] (`POST /api/booking/confirm`, `app.py:325-328`)
- Public MCP surface
