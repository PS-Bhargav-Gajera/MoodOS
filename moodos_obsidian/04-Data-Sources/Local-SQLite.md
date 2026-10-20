---
tags: [moodos, data-source, storage, sqlite]
---

# Local SQLite

The SQLite database `data/moodos.db` (`moodos/db.py`).

## Schema (`db.py:23`)

Six tables:

- `users(id, created_at)`
- `recommendation_events(id, user_id, query, bundle_json, created_at)` — written
  by `save_event` (`db.py:118`) at the end of every plan (`orchestrator.py:2390`);
  the returned `event_id` is surfaced in the bundle for feedback.
- `feedback(id, user_id, event_id, signal, note, long_term, created_at)` —
  written by `save_feedback` (`db.py:132`, [[Route Feedback]]).
- `knowledge_log(id, entity_key, action, created_at)` — from
  `KnowledgeStore.ingest` ([[Knowledge RAG Store]]).
- `mood_entries(...)` — the journal table: time buckets, current/desired mood,
  budget/duration, weather, plan kind/summary, `mood_reaction` (added by
  migration, `db.py:99-101`). Written via `insert_mood_entry` (`db.py:234`,
  from `journal.log_mood_entry`), read via `list_mood_entries` (`db.py:250`).
- `shown_items(id, user_id, kind, title_key, title, created_at)` — repeat
  suppression log from `record_shown` (`db.py:150`), trimmed to the last 200
  rows per user.

Every write holds `threading.Lock()`; the `bundle_json` blob is stored with
`ensure_ascii=False` (`db.py:124`). `init_db()` runs on startup
(`app.py:31-33` FastAPI lifespan).

## Connects to

- [[Route Feedback]] · [[Route Plan]] · [[Persistence]]
- [[Knowledge RAG Store]]

## Used by

- [[Architecture-Overview]] · [[Request Flow]]