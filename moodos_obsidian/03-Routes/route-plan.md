---
tags: [moodos, route, api]
---

# Route Plan

`POST /api/plan` → `app.py:85`

## Request

```json
{
  "message": "...",
  "user_id": "demo",
  "prompt": "/mood-night | null",
  "lat": 23.02 | null,
  "lon": 72.57 | null,
  "user_label": "Mumbai, Bandra | null",
  "ip": "1.2.3.4 | null"
}
```

`PlanRequest` model at `app.py:20-41`.

## Behavior

1. Rejects an empty message (400, `app.py:87`).
2. Filters loopback IPs → `None` (`app.py:90`).
3. `resolve_location(lat, lon, user_label, ip)` — confidence-ranked resolution
   ([[Location Resolution]], [[Route Location Resolve]]).
4. `handle_message(...)` (`orchestrator.py:246`) → plan **or** chat bundle.
5. Attaches the resolver audit (`source`, `confidence`, `gps_live`,
   `user_override`, city/area/state) to `bundle["location"]["resolver"]`
   (`app.py:100-109`).

Full downstream behavior: [[Request Flow]].

## Errors

- No explicit error mapper: an unhandled exception in the pipeline (e.g.
  [[Budget Fit Crash]]) surfaces as a 500, and the frontend shows a generic
  "Oops" (`app.js:583-593`).

## Connects to

- [[Request Flow]] · [[Location Resolution]] · [[Direct Chat]]
- [[Intent and Mood Extraction]] · [[Plan Assembly]] · [[Budget Fit Duration]]

## Used by

- [[Frontend]] (`app.js:573`) · [[00-Home]]