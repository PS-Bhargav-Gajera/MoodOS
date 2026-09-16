---
tags: [moodos, route, api]
---

# Route Location Resolve

`POST /api/location/resolve` → `app.py:113`

## Request

```json
{ "lat": 23.02 | null, "lon": 72.57 | null, "user_label": "Mumbai | null", "ip": "..." }
```

## Behavior

- IP loopback filter (`app.py:115-116`).
- Returns `resolve_location(...)` result — the full normalized location dict
  with `source`, `confidence`, `label`, `gps_live`, `user_override`, `city`,
  `area`, `state`, `country`, `display_name`.

Used by the frontend on every location change and before `/api/plan`
(`app.js:97-120`, `app.js:602-607`).

## Connects to

- [[Location Resolution]] · [[OpenStreetMap]]

## Used by

- [[Frontend]] · [[Route Plan]]