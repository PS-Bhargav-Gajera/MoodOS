---
tags: [moodos, core-logic, location]
---

# Location Resolution

Deciding "where am I?" with a confidence score
(`moodos/location.py`).

## Sources ranked by confidence

1. **User-entered label** (typing "Mumbai, Bandra") — confidence 0.98,
   `geocode_text` (Nominatim) (`location.py:22`).
2. **Browser GPS** — 0.82, reverse-geocoded (`reverse_geocode`,
   `providers.py:75`).
3. **IP location** — 0.45, city-level via ip-api (`ip_location`,
   `location.py:63`).
4. **Defaults** — configured `default_city` (Ahmedabad) at 0.1 when everything
   fails (`settings.default_lat/lon`, `config.py`).

`resolve_location(lat, lon, user_label, ip)` (`location.py:83`) picks the max
confidence candidate and reverse-geocodes it. Returns `source`, `confidence`,
`label`, `gps_live`, `user_override`, plus city/area/state/country.

## Consumers

- `/api/plan` audit block (`app.py:100-109`) and city labels in the bundle
  (`orchestrator.py:1398-1403`).
- `/api/location/resolve` ([[Route Location Resolve]]).
- `slots["city"]` default and `music_region` inference
  (`orchestrator.py:1246-1252`).
- Distance math for ranking: `_distance` (`orchestrator.py:150`)
  uses the resolved `lat/lon` for every candidate.

## Connects to

- [[OpenStreetMap]] · [[Route Location Resolve]] · [[Route Plan]]

## Used by

- [[Request Flow]] · [[Frontend]]