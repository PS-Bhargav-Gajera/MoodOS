"""User-facing error surfaces must never carry internal detail.

Two bugs motivated this file:

  * ``app.global_exception_handler`` returned ``str(exc)`` and the exception
    class name in the 500 body, leaking hostnames, paths and library names to
    any API consumer.
  * ``spotify.create_playlist`` returned the bare status ``create_failed``,
    which the frontend rendered verbatim. The underlying cause — a refresh
    token granted before the ``playlist-*`` scopes were requested — was
    invisible because the status code and Spotify's response body were both
    discarded instead of logged.

The rule under test throughout: the browser gets prose, the log gets detail.
"""

import ast
import inspect
import json
import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from moodos import spotify as sp

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------- fakes

class _Resp:
    """Minimal stand-in for an httpx.Response."""

    def __init__(self, status_code, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("response body is not json")
        return self._payload


class _FakeClient:
    def __init__(self, responses, calls):
        self._responses = list(responses)
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kw):
        self.calls.append(("GET", url))
        return self._responses.pop(0)

    def post(self, url, **kw):
        self.calls.append(("POST", url))
        return self._responses.pop(0)


def _install_client(monkeypatch, responses):
    calls: list = []
    monkeypatch.setattr(sp.httpx, "Client", lambda **kw: _FakeClient(responses, calls))
    return calls


def _connected(monkeypatch, tmp_path, scope=sp.SCOPES):
    """Point spotify at an isolated token file holding a usable grant."""
    monkeypatch.setattr(sp, "TOKEN_PATH", tmp_path / "spotify_tokens.json")
    sp._save_user({"access_token": "at", "refresh_token": "rt", "scope": scope})
    monkeypatch.setattr(sp, "_user_access_token", lambda: "at")
    return tmp_path / "spotify_tokens.json"


def _boom_route(client_app, name):
    """Register a route that raises a deliberately leaky exception."""
    @client_app.get(f"/api/_test/{name}")
    def _boom():
        raise RuntimeError("psycopg2 connect failed: hunter2@10.0.0.5 /srv/secret.db")

    return f"/api/_test/{name}"


# ------------------------------------------- 1. global handler must not leak

def test_global_handler_does_not_leak_exception_text():
    import app as appmod

    path = _boom_route(appmod.app, "leak")
    client = TestClient(appmod.app, raise_server_exceptions=False)

    res = client.get(path)
    assert res.status_code == 500
    body = res.text
    for secret in ("hunter2", "10.0.0.5", "psycopg2", "/srv/secret.db", "RuntimeError"):
        assert secret not in body, f"{secret!r} leaked to the client"

    payload = res.json()
    assert payload["code"] == "internal_error"
    assert payload["error_id"]
    assert payload["plan"] is None
    # "type" used to be the exception class name; it must be gone entirely.
    assert "type" not in payload


def test_global_handler_logs_traceback_with_matching_error_id(caplog):
    import app as appmod

    path = _boom_route(appmod.app, "logged")
    client = TestClient(appmod.app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR, logger="moodos.app"):
        res = client.get(path)

    error_id = res.json()["error_id"]
    messages = "\n".join(r.getMessage() for r in caplog.records)
    assert "Traceback" in messages
    assert error_id in messages
    # The detail that was kept out of the response has to be in the log.
    assert "hunter2" in messages


# ----------------------------------------- 2. sibling leak: memory wipe

def test_delete_all_memories_does_not_leak_exception(monkeypatch):
    import app as appmod

    def boom(*_a, **_k):
        raise RuntimeError("sqlite3 db is locked at C:/private/moodos.db")

    monkeypatch.setattr(appmod.mem0, "delete", boom)
    client = TestClient(appmod.app, raise_server_exceptions=False)

    res = client.delete("/api/memory/all?user_id=leak_test")
    assert "sqlite3 db is locked" not in res.text
    assert "C:/private" not in res.text
    assert res.json()["success"] is False
    assert res.json()["error_id"]


# ---------------------------------- 3. sibling leak: spotify oauth codes

def test_spotify_callback_does_not_echo_spotify_error_param():
    import app as appmod

    client = TestClient(appmod.app, raise_server_exceptions=False)
    res = client.get("/spotify/callback?error=access_denied&code=zz&state=ss")

    assert res.status_code == 400
    assert "access_denied" not in res.text
    assert "declined" in res.json()["detail"].lower()


def test_spotify_callback_does_not_echo_internal_exchange_code(monkeypatch):
    import app as appmod

    monkeypatch.setattr(
        appmod.spotify_api, "exchange_code",
        lambda code, state: {"ok": False, "error": "exchange_failed"},
    )
    client = TestClient(appmod.app, raise_server_exceptions=False)
    res = client.get("/spotify/callback?code=zz&state=ss")

    assert res.status_code == 400
    assert "exchange_failed" not in res.text


# ------------------------------- 4/5. create_failed: prose out, detail logged

def test_playlist_create_403_returns_friendly_message_not_status(monkeypatch, tmp_path):
    _connected(monkeypatch, tmp_path)
    _install_client(monkeypatch, [
        _Resp(200, {"id": "u1", "product": "premium"}),
        _Resp(403, {"error": {"status": 403, "message": "Forbidden"}}),
    ])

    out = sp.create_playlist("MoodOS — chill mix", ["spotify:track:x"], confirm=True)

    assert out["status"] == "create_failed"
    assert out["action"] == "reconnect"
    assert "playlist permission" in out["message"]
    assert out["executed"] is False
    # `status` legitimately stays in the payload as a machine-readable code; what
    # must never happen is the raw status or the raw HTTP response reaching the
    # copy the UI renders.
    assert "create_failed" not in out["message"]
    assert "403" not in out["message"]
    assert "Forbidden" not in json.dumps(out)


@pytest.mark.parametrize(
    "status_code, expected_action, expected_fragment",
    [
        (401, "reconnect", "expired"),
        (403, "reconnect", "playlist permission"),
        (429, "retry", "Too many"),
        (500, "retry", "try again"),
    ],
)
def test_playlist_create_maps_each_http_status_to_distinct_copy(
    monkeypatch, tmp_path, status_code, expected_action, expected_fragment
):
    _connected(monkeypatch, tmp_path)
    _install_client(monkeypatch, [
        _Resp(200, {"id": "u1", "product": "premium"}),
        _Resp(status_code, {"error": {"status": status_code, "message": "raw detail"}}),
    ])

    out = sp.create_playlist("mix", ["spotify:track:x"], confirm=True)

    assert out["status"] == "create_failed"
    assert out["action"] == expected_action
    assert expected_fragment.lower() in out["message"].lower()
    assert "raw detail" not in json.dumps(out)


def test_playlist_create_logs_status_and_spotify_reason(monkeypatch, tmp_path, caplog):
    _connected(monkeypatch, tmp_path)
    _install_client(monkeypatch, [
        _Resp(200, {"id": "u1", "product": "free"}),
        _Resp(403, {"error": {"status": 403, "reason": "INVALID_SCOPE", "message": "Forbidden"}}),
    ])

    with caplog.at_level(logging.WARNING, logger="moodos.spotify"):
        sp.create_playlist("mix", ["spotify:track:x"], confirm=True)

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "403" in logged
    assert "INVALID_SCOPE" in logged
    # product is what settles the "is this account Premium?" question outright.
    assert "product=free" in logged


def test_playlist_create_me_failure_logs_its_own_detail(monkeypatch, tmp_path, caplog):
    _connected(monkeypatch, tmp_path)
    _install_client(monkeypatch, [_Resp(401, {"error": {"status": 401, "message": "token expired"}})])

    with caplog.at_level(logging.WARNING, logger="moodos.spotify"):
        # A non-empty URI list so the call actually reaches GET /v1/me — an
        # empty list is now refused up front (see test_spotify_layers.py).
        out = sp.create_playlist("mix", ["spotify:track:x"], confirm=True)

    assert out["status"] == "auth_failed"
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "/v1/me" in logged
    assert "401" in logged


# --------------------------------------- 6. every status must have copy

def _status_literals(module) -> set:
    """Every status string the module can return.

    Picks up both ``{"status": "aborted"}`` and ``friendly("aborted")`` so the
    guard survives a refactor that changes how a status is produced.
    """
    tree = ast.parse(inspect.getsource(module))
    found: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, val in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant) and key.value == "status"
                        and isinstance(val, ast.Constant) and isinstance(val.value, str)):
                    found.add(val.value)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name == "friendly" and isinstance(node.args[0], ast.Constant):
                arg = node.args[0]
                if isinstance(arg.value, str):
                    found.add(arg.value)
    return found


def test_every_playlist_status_has_a_message():
    from moodos import mcp_server as ms

    seen = _status_literals(sp) | _status_literals(ms)
    # The reflection has to actually be finding things, or this test is vacuous.
    assert {"create_failed", "executed", "prepared"} <= seen

    missing = sorted(s for s in seen if s not in sp.USER_MESSAGES)
    assert not missing, f"statuses without user-facing copy: {missing}"

    for status in seen:
        entry = sp.USER_MESSAGES[status]
        assert entry["message"].strip(), status
        assert entry["action"], status
        # Copy must never contain the status token or a bare HTTP code.
        assert not re.search(r"\b(401|403|429|500)\b", entry["message"]), status


# ------------------------------- 7. root cause: a grant that cannot be widened

def test_stored_token_records_the_scope_actually_granted(monkeypatch, tmp_path):
    token_path = tmp_path / "spotify_tokens.json"
    monkeypatch.setattr(sp, "TOKEN_PATH", token_path)
    monkeypatch.setattr(sp, "_oauth_state", "state-123")
    _install_client(monkeypatch, [
        _Resp(200, {"access_token": "at", "refresh_token": "rt",
                    "expires_in": 3600, "scope": "user-read-email"}),
    ])

    assert sp.exchange_code("code", "state-123") == {"ok": True}
    saved = json.loads(token_path.read_text(encoding="utf-8"))
    assert saved["scope"] == "user-read-email"
    assert saved["access_token"] == "at"


def test_stale_grant_is_detected_and_prompts_reconnect(monkeypatch, tmp_path):
    _connected(monkeypatch, tmp_path, scope="user-read-email user-read-private")
    # A grant missing playlist-modify-* can never succeed; calling out is waste.
    monkeypatch.setattr(
        sp.httpx, "Client",
        lambda **kw: (_ for _ in ()).throw(AssertionError("must not call Spotify")),
    )

    assert sp.user_connected() is True
    assert sp.scope_gap() == list(sp.CREATE_SCOPES)
    assert sp.can_create_playlists() is False

    out = sp.create_playlist("mix", ["spotify:track:x"], confirm=True)
    assert out["status"] == "create_failed"
    assert out["action"] == "reconnect"
    assert out["scope_gap"] == list(sp.CREATE_SCOPES)
    assert "playlist permission" in out["message"]
    assert "create_failed" not in out["message"]


def test_unknown_scope_does_not_block_creation(monkeypatch, tmp_path):
    """A token file with no recorded scope is unknown, not empty."""
    _connected(monkeypatch, tmp_path, scope="")
    sp._save_user({"access_token": "at", "refresh_token": "rt"})

    assert sp.granted_scopes() == set()
    assert sp.scope_gap() == []
    assert sp.can_create_playlists() is True


def test_prepared_playlist_asks_for_reconnect_when_grant_is_stale(monkeypatch, tmp_path):
    from moodos import mcp_server as ms
    from moodos import providers as prov

    _connected(monkeypatch, tmp_path, scope="user-read-email")
    monkeypatch.setattr(prov, "search_music", lambda *a, **k: [])

    out = ms.mcp.create_playlist("calm acoustic evening", confirm=False)
    assert out["spotify_connected"] is False
    assert out["scope_gap"] == list(sp.CREATE_SCOPES)
    assert out["message"].strip()


# ------------------------------------------------------- 8. frontend

def test_frontend_never_renders_a_raw_status_string():
    src = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    # `${done.status}` is what shipped "create_failed" to the browser.
    assert re.search(r"\$\{\s*done\.status\s*\}", src) is None
    assert re.search(r"\$\{\s*done\.error\s*\}", src) is None
    assert "done.message" in src
    # The user needs a way to act on the message, not just read it.
    assert "/spotify/login" in src
