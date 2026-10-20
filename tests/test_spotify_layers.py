"""Spotify layer-by-layer coverage (Phase 3).

Seven layers were audited live against real Spotify
(``scripts/smoke_spotify_live.py``). This file pins the parts that must not
regress, using fakes so it stays hermetic:

  1. configuration          -- client id/secret + redirect URI
  2. client-credentials     -- app token for search
  3. /v1/search             -- track shape + the limit<=10 clamp
  4. OAuth authorize URL    -- scopes, state, redirect_uri, stale-state reject
  5. stored grant vs scopes -- scope_gap / can_create_playlists
  6. refresh exchange       -- refresh_token round-trip
  7. create_playlist        -- confirm gate, empty-refusal, status copy

The rule under test throughout: a dead/empty Spotify is reported, never turned
into a fabricated or empty playlist on the user's real account.
"""

from __future__ import annotations

import inspect
import json
from urllib.parse import parse_qs, urlparse

import pytest

from moodos import providers as p
from moodos import spotify as sp
from moodos.mcp_server import mcp

# ------------------------------------------------------------------ fakes


class _Resp:
    def __init__(self, status_code, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeClient:
    def __init__(self, responses, calls):
        # Share the list by reference: spotify.py builds a fresh
        # httpx.Client per request, and each one must keep consuming the SAME
        # queue or every call would replay response #1.
        self._responses = responses
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self._responses.pop(0)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self._responses.pop(0)


def _install(monkeypatch, responses):
    calls: list = []
    monkeypatch.setattr(sp.httpx, "Client", lambda **kw: _FakeClient(responses, calls))
    return calls


def _connected(monkeypatch, tmp_path, scope=sp.SCOPES):
    monkeypatch.setattr(sp, "TOKEN_PATH", tmp_path / "spotify_tokens.json")
    sp._save_user({"access_token": "at", "refresh_token": "rt", "scope": scope,
                   "expires": 9e12})
    monkeypatch.setattr(sp, "_user_access_token", lambda: "at")
    return tmp_path / "spotify_tokens.json"


def _track(name="Calm Evening", artist="Derrol", tid="abc123"):
    return {"id": f"spotify:{tid}", "uri": f"spotify:track:{tid}", "name": name,
            "artist": artist, "title": f"{name} — {artist}", "kind": "music",
            "source": "spotify", "duration_sec": 122, "duration_min": 2.0,
            "preview_url": None, "url": f"https://open.spotify.com/track/{tid}",
            "intensity": "low", "estimated_cost": 0}


# ------------------------------------------------- 1. configuration

def test_configured_requires_both_id_and_secret(monkeypatch):
    monkeypatch.setattr(sp.settings, "spotify_client_id", "id")
    monkeypatch.setattr(sp.settings, "spotify_client_secret", "")
    assert sp.configured() is False
    monkeypatch.setattr(sp.settings, "spotify_client_secret", "sec")
    assert sp.configured() is True


def test_redirect_uri_is_localhost_not_somewhere_else():
    # Spotify requires the redirect URI to match the dashboard EXACTLY. A
    # localhost/127.0.0.1 mismatch is the classic silent OAuth failure.
    uri = sp.settings.spotify_redirect_uri
    assert "127.0.0.1" in uri or "localhost" in uri
    assert uri.endswith("/spotify/callback")


# ------------------------------------------------- 2. client-credentials token

def test_app_access_token_parses_and_caches(monkeypatch):
    monkeypatch.setattr(sp.settings, "spotify_client_id", "id")
    monkeypatch.setattr(sp.settings, "spotify_client_secret", "sec")
    monkeypatch.setattr(sp, "_app_token", {"access": "", "expires": 0.0})
    _install(monkeypatch, [
        _Resp(200, {"access_token": "APP", "token_type": "Bearer", "expires_in": 3600}),
    ])
    assert sp.app_access_token() == "APP"
    assert sp._app_token["access"] == "APP"
    # second call is served from the cache, no extra HTTP
    assert sp.app_access_token() == "APP"


def test_app_access_token_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(sp.settings, "spotify_client_id", "id")
    monkeypatch.setattr(sp.settings, "spotify_client_secret", "sec")
    monkeypatch.setattr(sp, "_app_token", {"access": "", "expires": 0.0})
    _install(monkeypatch, [_Resp(400, {"error": "invalid_client"})])
    assert sp.app_access_token() is None


# ------------------------------------------------- 3. /v1/search shape + clamp

def test_search_tracks_clamps_limit_above_ten():
    # Spotify rejects track searches with limit > 10 (HTTP 400). The clamp
    # must stay in the source; live-verified in smoke_spotify_live.py.
    src = inspect.getsource(sp.search_tracks)
    assert "min(int(limit or 8), 10)" in src


def test_search_tracks_row_contract(monkeypatch):
    monkeypatch.setattr(sp, "app_access_token", lambda: "APP")
    monkeypatch.setattr(sp, "_user_access_token", lambda: None)
    body = {"tracks": {"items": [{
        "id": "abc123", "uri": "spotify:track:abc123", "name": "Calm Evening",
        "artists": [{"name": "Derrol"}], "duration_ms": 122000,
        "album": {"name": "Soft"}, "preview_url": None,
        "external_urls": {"spotify": "https://open.spotify.com/track/abc123"},
    }]}}
    _install(monkeypatch, [_Resp(200, body)])
    rows = sp.search_tracks("calm", limit=5)
    assert len(rows) == 1
    r = rows[0]
    for field in ("id", "uri", "name", "artist", "title", "kind", "source",
                  "duration_min", "duration_sec", "intensity", "preview_url", "url"):
        assert field in r, field
    assert r["id"] == "spotify:abc123"
    assert r["title"] == "Calm Evening — Derrol"
    assert r["source"] == "spotify"


def test_search_tracks_falls_through_a_403_token(monkeypatch):
    monkeypatch.setattr(sp, "app_access_token", lambda: "APP")
    monkeypatch.setattr(sp, "_user_access_token", lambda: "USER")
    good = {"tracks": {"items": [{
        "id": "ok", "uri": "spotify:track:ok", "name": "OK", "duration_ms": 60000,
        "artists": [{"name": "A"}], "external_urls": {},
    }]}}
    # user token 403s, app token succeeds
    _install(monkeypatch, [_Resp(403, {"error": {"status": 403}}), _Resp(200, good)])
    rows = sp.search_tracks("calm", limit=5)
    assert len(rows) == 1


# ------------------------------------------------- 4. OAuth authorize + state

def test_authorize_url_carries_every_required_param(monkeypatch):
    monkeypatch.setattr(sp.settings, "spotify_client_id", "cid")
    monkeypatch.setattr(sp.settings, "spotify_redirect_uri", "http://127.0.0.1:8000/spotify/callback")
    url = sp.authorize_url()
    q = parse_qs(urlparse(url).query)
    assert urlparse(url).netloc == "accounts.spotify.com"
    assert q["response_type"] == ["code"]
    assert q["client_id"] == ["cid"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8000/spotify/callback"]
    granted = set(q["scope"][0].split())
    assert {"playlist-modify-private", "playlist-modify-public",
            "user-read-private", "user-read-email"} <= granted
    assert len(q["state"][0]) >= 16


def test_stale_state_from_a_previous_login_is_rejected(monkeypatch):
    monkeypatch.setattr(sp.settings, "spotify_client_id", "cid")
    first = parse_qs(urlparse(sp.authorize_url()).query)["state"][0]
    sp.authorize_url()  # a second login replaces the state
    assert sp.exchange_code("code", first) == {"ok": False, "error": "invalid_state"}


def test_empty_state_is_rejected():
    assert sp.exchange_code("code", "") == {"ok": False, "error": "invalid_state"}


def test_exchange_code_saves_a_token_record(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "TOKEN_PATH", tmp_path / "tok.json")
    monkeypatch.setattr(sp.settings, "spotify_client_id", "cid")
    monkeypatch.setattr(sp.settings, "spotify_client_secret", "sec")
    sp.authorize_url()
    _install(monkeypatch, [_Resp(200, {
        "access_token": "AT", "refresh_token": "RT", "expires_in": 3600,
        "scope": "playlist-modify-private playlist-modify-public",
    })])
    assert sp.exchange_code("code", sp._oauth_state) == {"ok": True}
    saved = json.loads((tmp_path / "tok.json").read_text())
    assert saved["access_token"] == "AT"
    assert saved["refresh_token"] == "RT"
    assert "playlist-modify-public" in saved["scope"]


# ------------------------------------------------- 5. scopes

def test_scope_gap_is_empty_for_a_full_grant(monkeypatch, tmp_path):
    _connected(monkeypatch, tmp_path)
    assert sp.scope_gap() == []
    assert sp.can_create_playlists() is True


def test_scope_gap_lists_missing_create_scopes(monkeypatch, tmp_path):
    _connected(monkeypatch, tmp_path, scope="user-read-private")
    assert set(sp.scope_gap()) == {"playlist-modify-private", "playlist-modify-public"}
    assert sp.can_create_playlists() is False


def test_unknown_grant_scope_does_not_block(monkeypatch, tmp_path):
    # A token file that predates scope tracking must not be treated as "has
    # none" — the caller falls through to the live 403 path instead.
    monkeypatch.setattr(sp, "TOKEN_PATH", tmp_path / "tok.json")
    sp._save_user({"access_token": "at", "refresh_token": "rt"})
    assert sp.granted_scopes() == set()
    assert sp.scope_gap() == []


def test_refresh_updates_access_token_and_keeps_scope(monkeypatch, tmp_path):
    # Capture the real function BEFORE _connected replaces it with a stub.
    real_refresh = sp.__dict__["_user_access_token"]
    _connected(monkeypatch, tmp_path)
    monkeypatch.setattr(sp, "_user_access_token", real_refresh)
    monkeypatch.setattr(sp.settings, "spotify_client_id", "cid")
    monkeypatch.setattr(sp.settings, "spotify_client_secret", "sec")
    monkeypatch.setattr(sp, "_app_token", {"access": "", "expires": 0.0})
    monkeypatch.setattr(sp, "_load_user",
                        lambda: {"access_token": "old", "refresh_token": "rt",
                                 "expires": 0, "scope": sp.SCOPES})
    saved: dict = {}
    monkeypatch.setattr(sp, "_save_user", lambda d: saved.update(d))
    _install(monkeypatch, [_Resp(200, {
        "access_token": "NEW", "expires_in": 3600, "scope": sp.SCOPES,
    })])
    assert sp._user_access_token() == "NEW"
    assert saved["access_token"] == "NEW"
    assert "playlist-modify-public" in saved["scope"]


# ------------------------------------------------- 7. create_playlist

def test_confirm_false_aborts_without_calling_spotify(monkeypatch):
    calls = _install(monkeypatch, [])
    out = sp.create_playlist("mix", ["spotify:track:x"], confirm=False)
    assert out["status"] == "aborted"
    assert out["executed"] is False
    assert out["message"] and out["action"] == "none"
    assert calls == []


def test_empty_uris_never_creates_an_empty_playlist(monkeypatch, tmp_path):
    _connected(monkeypatch, tmp_path)
    calls = _install(monkeypatch, [])
    out = sp.create_playlist("mix", [], confirm=True)
    assert out["executed"] is False
    assert out["status"] == "create_failed"
    assert "no tracks" in out["message"].lower()
    assert calls == [], "no Spotify call may happen for an empty playlist"


def test_needs_auth_returns_an_authorize_url(monkeypatch):
    monkeypatch.setattr(sp, "_user_access_token", lambda: None)
    out = sp.create_playlist("mix", ["spotify:track:x"], confirm=True)
    assert out["status"] == "needs_auth"
    assert out["action"] == "connect"
    assert "accounts.spotify.com/authorize" in out["authorize_url"]


def test_scope_gap_short_circuits_before_any_spotify_call(monkeypatch, tmp_path):
    _connected(monkeypatch, tmp_path, scope="user-read-private")
    calls = _install(monkeypatch, [])
    out = sp.create_playlist("mix", ["spotify:track:x"], confirm=True)
    assert out["status"] == "create_failed"
    assert out["action"] == "reconnect"
    assert set(out["scope_gap"]) == {"playlist-modify-private", "playlist-modify-public"}
    assert calls == []


@pytest.mark.parametrize("code,action,fragment", [
    (401, "reconnect", "expired"),
    (403, "reconnect", "playlist permission"),
    (429, "retry", "too many"),
    (500, "retry", "try again"),
])
def test_each_create_failure_status_has_distinct_copy(
    monkeypatch, tmp_path, code, action, fragment
):
    _connected(monkeypatch, tmp_path)
    _install(monkeypatch, [
        _Resp(200, {"id": "u1", "product": "premium"}),
        _Resp(code, {"error": {"status": code, "message": "raw"}}),
    ])
    out = sp.create_playlist("mix", ["spotify:track:x"], confirm=True)
    assert out["status"] == "create_failed"
    assert out["action"] == action
    assert fragment in out["message"].lower()
    assert "raw" not in json.dumps(out)


def test_executed_result_reports_how_many_tracks_landed(monkeypatch, tmp_path):
    _connected(monkeypatch, tmp_path)
    _install(monkeypatch, [
        _Resp(200, {"id": "u1", "product": "premium"}),
        _Resp(201, {"id": "pl1", "external_urls": {"spotify": "https://open/pl"}}),
        _Resp(201, {"snapshot_id": "snap"}),
    ])
    out = sp.create_playlist("mix", ["spotify:track:a", "spotify:track:b"], confirm=True)
    assert out["executed"] is True
    assert out["playlist_url"] == "https://open/pl"
    assert out["tracks_added"] == 2
    assert out["tracks_requested"] == 2


def test_add_tracks_is_capped_at_spotify_hundred_uri_limit(monkeypatch, tmp_path):
    _connected(monkeypatch, tmp_path)
    calls = _install(monkeypatch, [
        _Resp(200, {"id": "u1", "product": "premium"}),
        _Resp(201, {"id": "pl1", "external_urls": {}}),
        _Resp(201, {"snapshot_id": "snap"}),
    ])
    uris = [f"spotify:track:{i}" for i in range(150)]
    out = sp.create_playlist("mix", uris, confirm=True)
    add_call = calls[-1]
    sent = add_call[2]["json"]["uris"]
    assert len(sent) == 100
    assert out["tracks_added"] == 100
    assert out["tracks_requested"] == 150


# --------------------------- playlist preparation must not invent an empty one

def test_prepare_refuses_when_spotify_returns_no_tracks(monkeypatch):
    monkeypatch.setattr(p, "search_music", lambda *a, **k: [])
    out = mcp.call("create_playlist", query="calm evening", confirm=False)
    assert out["executed"] is False
    assert out["requires_confirmation"] is False
    assert out["tracks"] == []
    assert "no tracks" in out["message"].lower() or "didn't return" in out["message"].lower()


def test_prepare_with_tracks_marks_confirmation_required(monkeypatch):
    monkeypatch.setattr(p, "search_music", lambda *a, **k: [_track()])
    out = mcp.call("create_playlist", query="calm evening", confirm=False)
    assert out["status"] == "prepared"
    assert out["requires_confirmation"] is True
    assert out["tracks"] and out["tracks"][0]["title"] == "Calm Evening — Derrol"
    assert out["provider"] == "spotify"


# --------------------------- a failed search must not poison the cache

def test_empty_spotify_result_is_not_cached(monkeypatch):
    # search_music used to ttl_cache.set() unconditionally, so one transient
    # Spotify outage was frozen for 20 minutes.
    monkeypatch.setattr(sp, "search_tracks", lambda *a, **k: [])
    from moodos.cache import ttl_cache

    ttl_cache._data = {}
    assert p.search_music("calm evening") == []
    assert not any(k.startswith("music:") for k in ttl_cache._data)


def test_non_empty_spotify_result_is_cached(monkeypatch):
    monkeypatch.setattr(sp, "search_tracks", lambda *a, **k: [_track()])
    from moodos.cache import ttl_cache

    ttl_cache._data = {}
    assert p.search_music("calm evening")
    assert any(k.startswith("music:") for k in ttl_cache._data)


# --------------------------- every status still has user-facing copy

def test_every_create_status_has_message_and_action():
    for status, entry in sp.USER_MESSAGES.items():
        assert entry.get("message"), status
        assert entry.get("action"), status
