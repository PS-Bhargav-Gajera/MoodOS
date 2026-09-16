---
tags: [moodos, tool, mcp]
---

# Confirm Movie Booking

MCP tool `confirm_movie_booking` → `actions.confirm_movie_booking`
(`moodos/mcp_server.py:34`).

## Signature

`confirm_movie_booking(confirmed: bool, show: dict | None = None) -> dict`

## Behavior

`actions.confirm_movie_booking` (`actions.py:100`): if `confirmed` is falsy →
`{status: aborted, executed: false}`. Otherwise returns
`{status: executed_mock, provider: "CinemaBookingProvider.MockProvider", show,
confirmation_code: "MOODOS-MOCK-4821"}`.

The booking is a **mock** — no real ticket is created. The route layer picks the
show from `list_showtimes()[show_index % 2]` (`app.py:141`).

## Connects to

- [[Mock cinema shows]] · [[Route Booking Confirm]]

## Used by

- [[Route Booking Confirm]] (`POST /api/booking/confirm`)
- Public MCP surface