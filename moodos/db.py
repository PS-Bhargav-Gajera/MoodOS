from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from moodos.config import settings

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    path: Path = settings.sqlite_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock:
        conn = _connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS recommendation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                query TEXT NOT NULL,
                bundle_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                event_id INTEGER,
                signal TEXT NOT NULL,
                note TEXT,
                long_term INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_key TEXT NOT NULL,
                action TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mood_entries (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id           TEXT NOT NULL,
                event_id          INTEGER,
                created_at        TEXT NOT NULL,
                local_date        TEXT NOT NULL,
                day_of_week       INTEGER NOT NULL,
                hour_local        INTEGER NOT NULL,
                time_bucket       TEXT NOT NULL,
                current_mood      TEXT,
                mood_valence      REAL NOT NULL DEFAULT 0,
                desired_mood      TEXT,
                desired_valence   REAL,
                mood_intensity    TEXT,
                intensity_score   INTEGER,
                social            TEXT,
                budget_inr        INTEGER,
                duration_hours    REAL,
                weather_condition TEXT,
                weather_rainy     INTEGER NOT NULL DEFAULT 0,
                temperature_c     REAL,
                plan_kind         TEXT,
                plan_summary      TEXT,
                stay_home         INTEGER NOT NULL DEFAULT 0,
                source            TEXT NOT NULL DEFAULT 'plan'
            );
            CREATE INDEX IF NOT EXISTS idx_mood_user_time
                ON mood_entries (user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_mood_user_date
                ON mood_entries (user_id, local_date);
            CREATE INDEX IF NOT EXISTS idx_mood_user_dow
                ON mood_entries (user_id, day_of_week);
            """
        )
        # --- migration: add mood_reaction column if missing ---
        cols = {row[1] for row in conn.execute("PRAGMA table_info(mood_entries)").fetchall()}
        if "mood_reaction" not in cols:
            conn.execute("ALTER TABLE mood_entries ADD COLUMN mood_reaction TEXT")
        conn.commit()
        conn.close()


def ensure_user(user_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT OR IGNORE INTO users (id, created_at) VALUES (?, ?)",
            (user_id, now),
        )
        conn.commit()
        conn.close()


def save_event(user_id: str, query: str, bundle: dict) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "INSERT INTO recommendation_events (user_id, query, bundle_json, created_at) VALUES (?,?,?,?)",
            (user_id, query, json.dumps(bundle, ensure_ascii=False), now),
        )
        conn.commit()
        event_id = int(cur.lastrowid)
        conn.close()
        return event_id


def save_feedback(user_id: str, event_id: int | None, signal: str, note: str, long_term: bool) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO feedback (user_id, event_id, signal, note, long_term, created_at) VALUES (?,?,?,?,?,?)",
            (user_id, event_id, signal, note, 1 if long_term else 0, now),
        )
        conn.commit()
        conn.close()


def get_event(event_id: int) -> dict | None:
    """Fetch a stored plan event (plan + slots) so feedback can write memory context."""
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT user_id, query, bundle_json FROM recommendation_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        conn.close()
    if not row:
        return None
    bundle = json.loads(row["bundle_json"] or "{}")
    return {
        "user_id": row["user_id"],
        "query": row["query"],
        "plan": bundle.get("plan"),
        "slots": bundle.get("slots"),
    }


def log_knowledge(entity_key: str, action: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO knowledge_log (entity_key, action, created_at) VALUES (?,?,?)",
            (entity_key, action, now),
        )
        conn.commit()
        conn.close()


_MOOD_COLUMNS = (
    "user_id", "event_id", "created_at", "local_date", "day_of_week", "hour_local",
    "time_bucket", "current_mood", "mood_valence", "desired_mood", "desired_valence",
    "mood_intensity", "intensity_score", "social", "budget_inr", "duration_hours",
    "weather_condition", "weather_rainy", "temperature_c", "plan_kind", "plan_summary",
    "stay_home", "source",
)


def insert_mood_entry(row: dict) -> int:
    """Insert one journal entry. Missing keys fall back to the column default."""
    values = [row.get(col) for col in _MOOD_COLUMNS]
    placeholders = ",".join("?" for _ in _MOOD_COLUMNS)
    with _lock:
        conn = _connect()
        cur = conn.execute(
            f"INSERT INTO mood_entries ({','.join(_MOOD_COLUMNS)}) VALUES ({placeholders})",
            values,
        )
        conn.commit()
        entry_id = int(cur.lastrowid)
        conn.close()
        return entry_id


def list_mood_entries(user_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT * FROM mood_entries WHERE user_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        ).fetchall()
        conn.close()
    return [dict(r) for r in rows]


def all_mood_entries(user_id: str, since: str | None = None) -> list[dict]:
    """Every entry for a user (optionally since an ISO date), oldest first."""
    query = "SELECT * FROM mood_entries WHERE user_id = ?"
    params: list = [user_id]
    if since:
        query += " AND created_at >= ?"
        params.append(since)
    query += " ORDER BY created_at ASC, id ASC"
    with _lock:
        conn = _connect()
        rows = conn.execute(query, params).fetchall()
        conn.close()
    return [dict(r) for r in rows]


def delete_mood_entry(user_id: str, entry_id: int) -> bool:
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "DELETE FROM mood_entries WHERE user_id = ? AND id = ?",
            (user_id, entry_id),
        )
        conn.commit()
        removed = cur.rowcount
        conn.close()
    return removed > 0


def delete_mood_entries(user_id: str) -> int:
    with _lock:
        conn = _connect()
        cur = conn.execute("DELETE FROM mood_entries WHERE user_id = ?", (user_id,))
        conn.commit()
        removed = cur.rowcount
        conn.close()
    return int(removed)


def update_mood_reaction(user_id: str, entry_id: int, reaction: str) -> bool:
    """Set a reaction only if the entry has none yet — the first reaction wins."""
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "UPDATE mood_entries SET mood_reaction = ? "
            "WHERE user_id = ? AND id = ? AND mood_reaction IS NULL",
            (reaction, user_id, entry_id),
        )
        conn.commit()
        updated = cur.rowcount
        conn.close()
    return updated > 0


def get_entry_reactions(user_id: str, entry_ids: list[int]) -> dict[int, str | None]:
    if not entry_ids:
        return {}
    placeholders = ",".join("?" for _ in entry_ids)
    with _lock:
        conn = _connect()
        rows = conn.execute(
            f"SELECT id, mood_reaction FROM mood_entries WHERE user_id = ? AND id IN ({placeholders})",
            [user_id, *entry_ids],
        ).fetchall()
        conn.close()
    return {row["id"]: row["mood_reaction"] for row in rows}


def get_mood_entry(user_id: str, entry_id: int) -> dict | None:
    """Fetch a single journal entry so the reaction handler can read its event_id."""
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT * FROM mood_entries WHERE user_id = ? AND id = ?",
            (user_id, entry_id),
        ).fetchone()
        conn.close()
    return dict(row) if row else None
