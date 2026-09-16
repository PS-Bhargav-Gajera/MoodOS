---
tags: [moodos, route, api]
---

# Route Booking Confirm

`POST /api/booking/confirm` → `app.py:139`

## Request

```json
{ "confirmed": true, "show_index": 0 }
```

## Behavior

- `actions.list_showtimes()[show_index % 2]` — pick the show (`app.py:141`).
- `actions.confirm_movie_booking(confirmed, show)` — mock execution
  (`actions.py:100`); returns `confirmation_code: MOODOS-MOCK-4821` for a
  confirmed booking, `aborted` otherwise. See [[Confirm Movie Booking]].

## Connects to

- [[Confirm Movie Booking]] · [[Mock cinema shows]]

## Used by

- [[Frontend]] (`app.js:455`) · [[00-Home]]