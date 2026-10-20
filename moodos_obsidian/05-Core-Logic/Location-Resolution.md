---
tags: [moodos, core-logic, location]
---

# Location Resolution

Deciding "where am I?" with a confidence score
(`moodos/location.py`).

## Sources ranked by confidence

1. **User-entered label** (typing "Mumbai, Bandra") — confidence 0.98,
   `geocode_text` (Nominatim) (`location.py:26`).
2. **Browser GPS** — 0.82 (0.92 → 0.35 as GPS accuracy degrades, `_gps_confidence`,
   `location.py:92`), reverse-geocoded (`reverse_geocode`,
   `providers.py:83`).
3. **IP location** — 0.45, city-level via **ipwho.is** (free, HTTPS, no key —
   it replaced the old cleartext `ip-api.com`) (`ip_location`,
   `location.py:66`).
4. **Defaults** — configured `default_city` (Ahmedabad) at 0.1 when everything
   fails (`_default_location`, `location.py:106`; `settings.default_lat/lon`,
   `config.py`).

`resolve_location(lat, lon, user_label, ip, accuracy_m)` (`location.py:124`)
picks the max confidence candidate and reverse-geocodes it. Returns `source`,
`confidence`, `label`, `gps_live`, `user_override`, plus city/area/state/country.

## Consumers

- `/api/plan` attaches the resolver audit block
  `bundle["location"]["resolver"]` (`app.py:144`, `app.py:168-178`) and city
  labels in the bundle (`orchestrator.py:2340-2344`).
- `/api/location/resolve` (`app.py:228`, [[Route Location Resolve]]).
- `location_service.get_current_location` delegates straight back here
  (`location_service.py:194-205`).
- `slots["city"]` default (`orchestrator.py:2075-2079`) and `music_region`
  inference (`orchestrator.py:2152`).
- Distance math for ranking: `_distance` (`orchestrator.py:334`)
  uses the resolved `lat/lon` for every candidate.

## Connects to

- [[OpenStreetMap]] · [[Route Location Resolve]] · [[Route Plan]]

## Used by

- [[Request Flow]] · [[Frontend]]