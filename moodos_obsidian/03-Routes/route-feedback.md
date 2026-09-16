---
tags: [moodos, route, api]
---

# Route Feedback

`POST /api/feedback` → `app.py:120`

## Request

```json
{ "user_id": "demo", "event_id": 123 | null, "signal": "like|dislike|flag",
  "note": "I prefer..., optional", "repeats": 1-10 }
```

## Behavior

- If `note` set → `mem0.add_if_long_term(user_id, note, repeats)`
  (`memory.py:189`): an explicit note repeated ≥2 times (or >20 chars and not
  "today"-based) becomes a long-term memory with rising confidence.
- Else if `signal == "like"` → stores "User enjoyed the last low-intensity
  experience" as long-term when repeats allow (`app.py:127-129`).
- Always calls `save_feedback` ([[Local SQLite]], `db.py:85`).

Frontend wires this to the like/dislike buttons after a plan (`app.js:433`).

## Connects to

- [[Mem0]] · [[Local SQLite]] · [[Persistence]]

## Used by

- [[Frontend]] · [[00-Home]]