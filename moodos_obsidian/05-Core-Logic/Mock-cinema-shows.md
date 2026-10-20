---
tags: [moodos, core-logic, mock, booking]
---

# Mock cinema shows

Estimated showtimes and mock booking actions (`moodos/actions.py`) — there is
**no real BMS integration** and no canned venue/title list: titles come live
from TMDB, times/prices are static estimates.

## Data

- `_EST_TIMES` (`actions.py:9`) — 5 evening slots: 17:50, 18:40, 19:15, 20:00,
  21:10; `_EST_PRICES` (`actions.py:10`) — ₹220, 230, 250, 260, 240.
- Each show pairs a **live TMDB now-playing title** with `_EST_TIMES[i % 5]` /
  `_EST_PRICES[i % 5]` (`actions.py:26-50`). Fields: `provider:
  "TMDB now playing"`, `movie`, `tmdb_id`, `overview`, `poster_url`,
  `original_language`, `release_date`, `time`, `price_inr`,
  `seats: "check at venue"`, `showtime_estimated: true`, plus the caller's
  `lat`/`lon` (`cinema` stays `None` — the venue is attached by
  [[Movie Candidates]]).
- Not cached in itself: only the underlying `tmdb_now_playing` titles are
  cached (3 h, `providers.py:1032`).

## Functions

- `list_showtimes(lat, lon, limit=4, region="IN", movies=None)`
  (`actions.py:13`) — pairs TMDB now-playing films with the estimated times;
  no distance sorting (the caller maps shows onto real OSM venues).
- `prepare_movie_booking(show_index, show)` (`actions.py:54`) — `{status:
  prepared, requires_confirmation: true, show, expires_at (+8 min), note:
  no money is charged / showtime is an estimate}`; falls back to a generic
  show when nothing is available (`actions.py:55-64`).
- `confirm_movie_booking(confirmed, show)` (`actions.py:74`) — `{status:
  recorded, executed: true, provider: "MoodOS (no live ticketing — confirm at
  the cinema)", confirmation_code: f"MOODOS-{HHMMSS}"}` (`actions.py:82`);
  `confirmed=false` → `{status: aborted}`.
- `prepare_food_order(item)` (`actions.py:86`) — prepared mock, no consumer.

These power [[Prepare Movie Booking]], [[Confirm Movie Booking]], the booking
routes, and the showtime half of [[Movie Candidates]].

**Honesty note**: every show carries `showtime_estimated: true` and
`seats: "check at venue"` (`actions.py:46-47`); candidates get a
`showtime_disclaimer` (`orchestrator.py:298-300`) that is copied onto plan
steps (`orchestrator.py:1226-1227`), and the LLM prompt forbids inventing
showtimes (`llm.py:19`).

## Connects to

- [[Prepare Movie Booking]] · [[Confirm Movie Booking]] · [[Movie Candidates]]
- [[Route Booking Prepare]] · [[Route Booking Confirm]]

## Used by

- [[Frontend]] booking flow · [[Request Flow]]