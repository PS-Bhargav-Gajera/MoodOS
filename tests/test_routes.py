"""TestClient coverage for the memory, journal, spotify, and booking routes.

Before this file, only the error paths of those surfaces were tested (in
test_errors.py) plus journal/react (test_preferences.py); the happy paths and
the remaining routes had no HTTP-level coverage at all.

Isolation: every test runs against its own tmp_path SQLite DB and its own
tmp_path mem0 JSON file (AGENTS.md: tests must never touch data/*.db or
data/spotify_tokens.json, and rows written by one test must not leak into
another). The Mem0 cloud is disabled so no test can reach api.mem0.ai.
"""

import pytest
from fastapi.testclient import TestClient

import app as appmod
from app import app
from moodos import journal as journalmod
from moodos import memory as memorymod
from moodos.config import settings
from moodos.db import init_db
from moodos.memory import mem0

USER = "routes_test_user"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Point the DB and the local memory file at this test's tmp_path."""
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "moodos.db")
    monkeypatch.setattr(memorymod, "MEM_PATH", tmp_path / "mem0_users.json")
    monkeypatch.setattr(mem0, "cloud", None)
    init_db()
    mem0.delete(USER)
    journalmod.clear_journal(USER)
    yield
    mem0.delete(USER)
    journalmod.clear_journal(USER)


@pytest.fixture()
def client():
    return TestClient(app)


# ---------------------------------------------------------------- memory


def test_mem0_list_returns_seeded_memory_with_category(client):
    mem0.add(USER, "Likes quiet cafes", category="preference")

    res = client.get("/api/mem0", params={"user_id": USER})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    texts = [m["text"] for m in data["memories"]]
    assert "Likes quiet cafes" in texts
    assert all(m.get("category") for m in data["memories"])


def test_mem0_list_filters_by_category(client):
    mem0.add(USER, "Likes quiet cafes", category="preference")
    mem0.add(USER, "Watched a movie yesterday", category="episodic")

    res = client.get("/api/mem0", params={"user_id": USER, "categories": "episodic"})
    rows = res.json()["memories"]
    assert [m["text"] for m in rows] == ["Watched a movie yesterday"]


def test_mem0_remove_wipes_user_memories(client):
    mem0.add(USER, "Likes quiet cafes", category="preference")

    res = client.post("/api/mem0/remove", params={"user_id": USER})
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert mem0.list(USER) == []


def test_mem0_update_one_rewrites_text(client):
    mem0.add(USER, "Likes quiet cafes", category="preference")
    memory_id = mem0.list(USER)[0]["id"]

    res = client.put(
        f"/api/mem0/{memory_id}",
        json={"user_id": USER, "text": "Likes loud cafes", "metadata": None},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert mem0.list(USER)[0]["text"] == "Likes loud cafes"


def test_mem0_delete_one_removes_single_memory(client):
    mem0.add(USER, "Likes quiet cafes", category="preference")
    mem0.add(USER, "Enjoys movies", category="preference")
    memory_id = mem0.list(USER)[0]["id"]

    res = client.delete(f"/api/mem0/{memory_id}", params={"user_id": USER})
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    remaining = [m["text"] for m in mem0.list(USER)]
    assert len(remaining) == 1


def test_delete_all_memories_happy_path(client):
    mem0.add(USER, "Likes quiet cafes", category="preference")

    res = client.delete("/api/memory/all", params={"user_id": USER})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["message"] == "All memories cleared."
    assert data["deleted"]["local"] == 1


# ---------------------------------------------------------------- journal


def _log_entry(user_id=USER, mood="tired"):
    return journalmod.log_mood_entry(
        user_id, {"current_mood": mood}, plan={"steps": [{"kind": "cafe"}]}
    )


def test_journal_list_returns_logged_entries(client):
    _log_entry()
    _log_entry(mood="happy")

    res = client.get("/api/journal", params={"user_id": USER})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert len(data["entries"]) == 2


def test_journal_list_clamps_limit(client):
    _log_entry()
    res = client.get("/api/journal", params={"user_id": USER, "limit": 99999})
    assert res.status_code == 200  # clamped to 500, not rejected


def test_journal_trends_payload(client):
    _log_entry()
    res = client.get("/api/journal/trends", params={"user_id": USER, "weeks": 2})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["total_entries"] == 1
    assert data["weeks"] == 2
    assert "heatmap" in data and "insight" in data


def test_journal_strip_payload(client):
    _log_entry()
    res = client.get("/api/journal/strip", params={"user_id": USER})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["total_shown"] == 1
    assert len(data["entries"]) == 1


def test_journal_rejects_unknown_reaction(client):
    entry_id = _log_entry()
    res = client.post("/api/journal/react", json={
        "user_id": USER, "entry_id": entry_id, "reaction": "angry",
    })
    assert res.status_code == 400
    assert "must be one of" in res.json()["detail"]


def test_journal_react_applies_once(client):
    entry_id = _log_entry()
    res = client.post("/api/journal/react", json={
        "user_id": USER, "entry_id": entry_id, "reaction": "sad",
    })
    assert res.status_code == 200
    assert res.json()["applied"] is True

    # First reaction wins: a second one on the same entry is a no-op.
    res2 = client.post("/api/journal/react", json={
        "user_id": USER, "entry_id": entry_id, "reaction": "happy",
    })
    assert res2.status_code == 200
    assert res2.json()["applied"] is False


def test_journal_delete_one_and_clear(client):
    keep = _log_entry()
    drop = _log_entry()

    res = client.delete(f"/api/journal/{drop}", params={"user_id": USER})
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    remaining = [e["id"] for e in journalmod.recent_entries(USER)]
    assert remaining == [keep]

    res2 = client.delete("/api/journal", params={"user_id": USER})
    assert res2.status_code == 200
    assert res2.json() == {"ok": True, "removed": 1}
    assert journalmod.recent_entries(USER) == []


# ---------------------------------------------------------------- spotify


def test_spotify_login_not_configured_returns_400(client, monkeypatch):
    monkeypatch.setattr(appmod.spotify_api, "configured", lambda: False)
    res = client.get("/spotify/login")
    assert res.status_code == 400
    assert res.json()["detail"] == "Spotify is not configured"


def test_spotify_login_redirects_to_authorize(client, monkeypatch):
    monkeypatch.setattr(appmod.spotify_api, "configured", lambda: True)
    monkeypatch.setattr(
        appmod.spotify_api, "authorize_url", lambda: "https://accounts.spotify.com/authorize?x=1"
    )
    res = client.get("/spotify/login", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"].startswith("https://accounts.spotify.com/authorize")


def test_spotify_callback_success_redirects_home(client, monkeypatch):
    monkeypatch.setattr(
        appmod.spotify_api, "exchange_code",
        lambda code, state: {"ok": True},
    )
    res = client.get("/spotify/callback?code=abc&state=xyz", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"] == "/"


def test_playlist_prepare_forwards_confirm_false(client, monkeypatch):
    seen = {}

    def fake_call(name, **kw):
        seen["name"] = name
        seen.update(kw)
        return {"prepared": True, "confirm": kw.get("confirm")}

    monkeypatch.setattr(appmod.mcp, "call", fake_call)
    res = client.post("/api/playlist/prepare", params={"query": "lofi beats", "seed": 3})
    assert res.status_code == 200
    assert res.json() == {"prepared": True, "confirm": False}
    assert seen["name"] == "create_playlist"
    assert seen["query"] == "lofi beats"
    assert seen["seed"] == 3


def test_playlist_confirm_forwards_body(client, monkeypatch):
    seen = {}

    def fake_call(name, **kw):
        seen["name"] = name
        seen.update(kw)
        return {"created": kw.get("confirm")}

    monkeypatch.setattr(appmod.mcp, "call", fake_call)
    res = client.post("/api/playlist/confirm", json={"query": "calm", "confirmed": True})
    assert res.status_code == 200
    assert res.json() == {"created": True}
    assert seen["name"] == "create_playlist"
    assert seen["confirm"] is True


# ---------------------------------------------------------------- booking


_CANNED_SHOWS = [
    {"movie": "Film A", "lat": 23.0, "lon": 72.5, "time": "17:50", "price_inr": 220},
    {"movie": "Film B", "lat": 23.1, "lon": 72.6, "time": "18:40", "price_inr": 230},
]


def test_booking_prepare_returns_prepared_show(client, monkeypatch):
    monkeypatch.setattr(appmod.actions, "list_showtimes", lambda *a, **kw: list(_CANNED_SHOWS))
    res = client.post("/api/booking/prepare", params={"show_index": 1})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "prepared"
    assert data["requires_confirmation"] is True
    assert data["show"]["movie"] == "Film A"  # show_index 1 -> min(1,0) picks shows[0]


def test_booking_confirm_aborted(client, monkeypatch):
    monkeypatch.setattr(appmod.actions, "list_showtimes", lambda *a, **kw: list(_CANNED_SHOWS))
    res = client.post("/api/booking/confirm", json={"confirmed": False, "show_index": 0})
    assert res.status_code == 200
    assert res.json() == {"status": "aborted", "executed": False}


def test_booking_confirm_records_with_show_passthrough(client, monkeypatch):
    monkeypatch.setattr(appmod.actions, "list_showtimes", lambda *a, **kw: list(_CANNED_SHOWS))
    res = client.post("/api/booking/confirm", json={"confirmed": True, "show_index": 1})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "recorded"
    assert data["executed"] is True
    assert data["show"]["movie"] == "Film B"  # show_index % 2 picks the 2nd show
    assert data["confirmation_code"].startswith("MOODOS-")
