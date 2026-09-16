---
tags: [moodos, core-logic, mock, booking]
---

# Mock cinema shows

Canned showtimes and mock booking actions (`moodos/actions.py`) — there is **no
real BMS integration**.

## Data

`CINEMA_SHOWS` (`actions.py:7`): 4 filtered entries — PVR Acropolis, Cinepolis
Alpha One, PVR Mutiplex Motera (all Ahmedabad) + INOX Iscon, with movies
"The Lunchbox", "Paddington in Peru", "Everything Everywhere All at Once",
"Little Miss Sunshine", times 17:50-20:00, ₹220-260, `seats: available`.
`MUSIC_PLAYLIST_NAMES` (`actions.py:50`) is a leftover static list of playlist
names (not used by the live playlist flow — [[Create Playlist]] builds names
from query keywords).

## Functions

- `list_showtimes(lat, lon, limit=4)` (`actions.py:69`) — sorts by haversine
  distance from the user (nearest first).
- `prepare_movie_booking(i)` (`actions.py:89`) — `{status: prepared, ...
  expires_at +8min, note: no money charged until confirm}`.
- `confirm_movie_booking(confirmed, show)` (`actions.py:100`) — mock execution,
  returns `MOODOS-MOCK-4821`.
- `prepare_food_order(item)` (`actions.py:112`) — prepared mock, no consumer.

These power [[Prepare Movie Booking]], [[Confirm Movie Booking]], the booking
routes, and the showtime half of [[Movie Candidates]].

**Honesty note**: showtimes are labeled `MockProvider` in data (`actions.py:9`)
and step blurbs carry a showtime disclaimer (`orchestrator.py:553-555`).

## Connects to

- [[Prepare Movie Booking]] · [[Confirm Movie Booking]] · [[Movie Candidates]]
- [[Route Booking Prepare]] · [[Route Booking Confirm]]

## Used by

- [[Frontend]] booking flow · [[Request Flow]]