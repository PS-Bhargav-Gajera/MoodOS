---
tags: [moodos, architecture, persistence]
---

# Persistence

Where MoodOS stores state. All paths live under `data/` (from `config.py`
`DATA_DIR`).

| Store | File | Written by | Notes |
|---|---|---|---|
| SQLite | `data/moodos.db` | `db.py` | users, recommendation_events, feedback, knowledge_log |
| User memory | `data/mem0_users.json` | `memory.py` `LocalMemory` | local fallback when Mem0 Cloud is off |
| Knowledge RAG | `data/seed_knowledge.json` + `data/acquired_knowledge.json` | `rag.py` | TF-IDF doc store |
| TTL cache | `data/ttl_cache.json` | `cache.py` | all provider lookups |
| Spotify OAuth | `data/spotify_tokens.json` | `spotify.py` | user access/refresh tokens |

## SQLite schema (`db.py:22`)

- `users(id PK, created_at)`
- `recommendation_events(id, user_id, query, bundle_json, created_at)`
- `feedback(id, user_id, event_id, signal, note, long_term, created_at)`
- `knowledge_log(id, entity_key, action, created_at)`

Every write holds `threading.Lock()`. `bundle_json` is stored with
`ensure_ascii=False` (`db.py:77`). `/api/feedback` uses
`mem0.add_if_long_term(...)` (`memory.py:189`) before `save_feedback`
(`app.py:120-131`, [[Route Feedback]]).

`init_db()` is a no-op-safe startup hook (`app.py:62-64`).

## Cache semantics (`cache.py`)

`TTLCache.get` drops expired keys on read; `set` rewrites the whole file under
lock. Provider keys embed their discriminating inputs (e.g. `music:{q}|{country}
|seed={seed}`) — see each note in 04-Data-Sources for TTLs.

## Connects to

- [[Local SQLite]] · [[Local JSON Memory]] · [[Knowledge RAG Store]] · [[TTL Cache]] · [[Spotify]]
- [[Route Feedback]] · [[Route Plan]]

## Used by

- [[Architecture-Overview]]
- [[Request Flow]]