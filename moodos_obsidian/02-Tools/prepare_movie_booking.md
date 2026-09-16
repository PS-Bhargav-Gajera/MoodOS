---
tags: [moodos, tool, mcp]
---

# Prepare Movie Booking

MCP tool `prepare_movie_booking` → `lambda i=0: actions.prepare_movie_booking(i)`
(`moodos/mcp_server.py:33`).

## Signature

`prepare_movie_booking(show_index: int = 0) -> dict`

## Behavior

`actions.prepare_movie_booking` (`actions.py:89`) picks a show from the static
`CINEMA_SHOWS` mock list ([[Mock cinema shows]]), returns `status: prepared`,
`requires_confirmation: True`, an 8-minute expiry, and an explicit guarantee
that **no money is charged until confirmed**.

Called by `POST /api/booking/prepare` ([[Route Booking Prepare]]), invoked from
the frontend "Book" flow (`app.js:448`).

## Connects to

- [[Mock cinema shows]] · [[Movie Candidates]]
- [[Route Booking Prepare]]

## Used by

- [[Route Booking Prepare]]
- Public MCP surface