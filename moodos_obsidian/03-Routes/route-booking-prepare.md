---
tags: [moodos, route, api]
---

# Route Booking Prepare

`POST /api/booking/prepare` → `app.py:134`

## Behavior

`actions.prepare_movie_booking(show_index)` — returns a mock show with
`status: prepared`, 8-minute expiry, "no money charged until confirmed"
(`actions.py:89`). See [[Prepare Movie Booking]].

Frontend: "Book" button preview step (`app.js:444-449`).

## Connects to

- [[Prepare Movie Booking]] · [[Mock cinema shows]]

## Used by

- [[Frontend]] · [[00-Home]]