---
tags: [moodos, data-source, storage, sqlite]
---

# Local SQLite

The SQLite database `data/moodos.db` (`moodos/db.py`).

## Schema (`db.py:22`)

- `users(id, created_at)`
- `recommendation_events(id, user_id, query, bundle_json, created_at)` — written
  by `save_event` at the end of every plan (`orchestrator.py:1444`); the
  returned `event_id` is surfaced in the bundle for feedback.
- `feedback(id, user_id, event_id, signal, note, long_term, created_at)` —
  written by [[Route Feedback]].
- `knowledge_log(id, entity_key, action, created_at)` — from
  `KnowledgeStore.ingest` ([[Knowledge RAG Store]]).

Every write holds `threading.Lock()`; the `bundle_json` blob is stored with
`ensure_ascii=False` (`db.py:77`). `init_db()` runs on startup (`app.py:62-64`).

## Connects to

- [[Route Feedback]] · [[Route Plan]] · [[Persistence]]
- [[Knowledge RAG Store]]

## Used by

- [[Architecture-Overview]] · [[Request Flow]]