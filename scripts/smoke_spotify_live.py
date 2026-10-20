"""Live Spotify smoke, layer by layer.

Deliberately NOT part of pytest: it talks to real Spotify and reads the real
data/spotify_tokens.json. Run by hand when auditing:

    python scripts/smoke_spotify_live.py

Each layer prints the exact HTTP status and the body Spotify returned so a
failure is attributable to one layer rather than "Spotify is broken".
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from moodos import spotify as sp  # noqa: E402
from moodos.config import settings  # noqa: E402

TIMEOUT = 20.0
_failures: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'ok' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


def _brief(body: object, limit: int = 300) -> str:
    try:
        text = json.dumps(body)
    except Exception:
        text = str(body)
    return " ".join(text.split())[:limit]


def layer1_config() -> bool:
    print("\n=== Layer 1: configuration ===")
    _check("SPOTIFY_CLIENT_ID set", bool(settings.spotify_client_id),
           f"len={len(settings.spotify_client_id or '')}")
    _check("SPOTIFY_CLIENT_SECRET set", bool(settings.spotify_client_secret),
           f"len={len(settings.spotify_client_secret or '')}")
    uri = settings.spotify_redirect_uri
    print(f"  redirect_uri = {uri!r}")
    # Spotify requires the redirect URI to match an entry in the app dashboard
    # EXACTLY, including scheme and port. The most common silent failure is
    # using localhost here while the dashboard has 127.0.0.1 (or vice versa).
    _check("redirect_uri uses 127.0.0.1 or localhost", "127.0.0.1" in uri or "localhost" in uri)
    _check("spotify.configured()", sp.configured())
    return sp.configured()


def layer2_app_token() -> str | None:
    print("\n=== Layer 2: client-credentials app token ===")
    if not sp.configured():
        _check("configured", False, "no client id/secret")
        return None
    raw = f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()
    try:
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(
                "https://accounts.spotify.com/api/token",
                headers={
                    "Authorization": "Basic " + base64.b64encode(raw).decode(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials"},
            )
        print(f"  POST /api/token -> {r.status_code}")
        print(f"  body: {_brief(_safe_json(r))}")
        _check("token endpoint 200", r.status_code == 200)
        tok = sp.app_access_token()
        _check("app_access_token() returns a token", bool(tok),
               f"prefix={(tok or '')[:12]}...")
        return tok
    except Exception as exc:
        _check("token endpoint reachable", False, repr(exc))
        return None


def _safe_json(r: httpx.Response) -> object:
    try:
        return r.json()
    except Exception:
        return r.text


def layer3_search(token: str | None) -> None:
    print("\n=== Layer 3: /v1/search (track query) ===")
    if not token:
        _check("search skipped", False, "no app token")
        return
    for market in ("IN", "US"):
        try:
            with httpx.Client(timeout=TIMEOUT) as c:
                r = c.get(
                    "https://api.spotify.com/v1/search",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"q": "lofi study", "type": "track", "limit": 5,
                            "market": market},
                )
            body = _safe_json(r)
            items = ((body or {}).get("tracks") or {}).get("items") or []
            print(f"  GET /v1/search market={market} -> {r.status_code}  "
                  f"items={len(items)}")
            _check(f"search market={market} 200", r.status_code == 200,
                   _brief(body, 120))
            _check(f"search market={market} returns tracks", len(items) > 0)
        except Exception as exc:
            _check(f"search market={market} reachable", False, repr(exc))

    # The module clamps limit > 10 because Spotify rejects it with 400.
    try:
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.get(
                "https://api.spotify.com/v1/search",
                headers={"Authorization": f"Bearer {token}"},
                params={"q": "jazz", "type": "track", "limit": 20, "market": "IN"},
            )
        print(f"  GET /v1/search limit=20 -> {r.status_code}  "
              f"(Spotify rejects >10; the module must clamp before this point)")
        _check("raw limit=20 is rejected by Spotify (documents the clamp)",
               r.status_code >= 400)
    except Exception as exc:
        _check("limit probe reachable", False, repr(exc))

    print("  via module:")
    rows = sp.search_tracks("calm evening", limit=50, market="IN")
    _check("search_tracks() with limit=50 returns <= 10 rows", len(rows) <= 10,
           f"rows={len(rows)}")
    if rows:
        r0 = rows[0]
        for field in ("id", "uri", "name", "artist", "title", "kind", "source",
                      "duration_min", "duration_sec", "intensity", "preview_url", "url"):
            _check(f"row has {field}", field in r0, f"value={r0.get(field)!r}")
        _check("id is namespaced spotify:", str(r0.get("id", "")).startswith("spotify:"))
        _check("source is spotify", r0.get("source") == "spotify")
        print(f"  first row: {r0.get('title')}  dur={r0.get('duration_min')}min")


def layer4_oauth_redirect(token: str | None) -> None:
    print("\n=== Layer 4: OAuth authorize URL + auth-code redirect URI ===")
    url = sp.authorize_url()
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(url).query)
    print(f"  authorize_url host={urlparse(url).netloc} path={urlparse(url).path}")
    _check("authorize endpoint is accounts.spotify.com/authorize",
           urlparse(url).netloc == "accounts.spotify.com")
    _check("response_type=code", q.get("response_type") == ["code"])
    _check("client_id present", bool(q.get("client_id")))
    _check("redirect_uri present and matches settings",
           q.get("redirect_uri") == [settings.spotify_redirect_uri])
    granted = set((q.get("scope") or [""])[0].split())
    print(f"  requested scopes ({len(granted)}): {sorted(granted)}")
    for needed in ("playlist-modify-private", "playlist-modify-public",
                   "user-read-private", "user-read-email"):
        _check(f"scope {needed} requested", needed in granted)
    _check("state is non-empty and looks random",
           len((q.get("state") or [""])[0]) >= 16)

    # A second login regenerates state; the first link must now fail.
    first_state = (q.get("state") or [""])[0]
    sp.authorize_url()
    res = sp.exchange_code("bogus-code", first_state)
    _check("stale/replaced state is rejected",
           res == {"ok": False, "error": "invalid_state"}, str(res))
    res2 = sp.exchange_code("bogus-code", "")
    _check("empty state is rejected",
           res2 == {"ok": False, "error": "invalid_state"}, str(res2))


def layer5_scopes() -> None:
    print("\n=== Layer 5: stored grant vs playlist scopes ===")
    connected = sp.user_connected()
    print(f"  TOKEN_PATH exists={sp.TOKEN_PATH.exists()} connected={connected}")
    data = sp._load_user()
    safe = {k: (v[:14] + "..." if isinstance(v, str) and k.endswith("token") else v)
            for k, v in data.items()}
    print(f"  stored keys={sorted(data)}  values={safe}")
    granted = sp.granted_scopes()
    gap = sp.scope_gap()
    print(f"  granted_scopes({len(granted)}): {sorted(granted)}")
    print(f"  scope_gap: {gap}")
    _check("granted_scopes parses from the stored record", bool(granted) == connected,
           f"connected={connected}")
    _check("scope_gap is a subset of the create scopes",
           set(gap) <= set(sp.CREATE_SCOPES))
    _check("can_create_playlists() == connected and no gap",
           sp.can_create_playlists() == (connected and not gap))
    if connected and not gap:
        _check("grant covers playlist-modify-private",
               "playlist-modify-private" in granted)
        _check("grant covers playlist-modify-public",
               "playlist-modify-public" in granted)
    else:
        print("  (not connected or gap present -- a create_playlist call will "
              "return needs_auth / reconnect, which is the correct behaviour)")


def layer6_refresh(token: str | None) -> None:
    print("\n=== Layer 6: refresh-token exchange ===")
    data = sp._load_user()
    refresh = data.get("refresh_token")
    if not refresh:
        _check("refresh layer skipped", True, "no stored refresh_token")
        return
    raw = f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()
    try:
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(
                "https://accounts.spotify.com/api/token",
                headers={
                    "Authorization": "Basic " + base64.b64encode(raw).decode(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "refresh_token", "refresh_token": refresh},
            )
        body = _safe_json(r)
        print(f"  POST /api/token grant_type=refresh_token -> {r.status_code}")
        print(f"  body: {_brief(body)}")
        _check("refresh 200", r.status_code == 200, _brief(body))
        if r.status_code == 200:
            scope = (body or {}).get("scope")
            print(f"  refreshed grant scope: {scope}")
            _check("refreshed access_token present",
                   bool((body or {}).get("access_token")))
            _check("refreshed grant still covers playlist-modify-public",
                   bool(scope) and "playlist-modify-public" in scope.split())
            _check("_user_access_token() returns a token",
                   bool(sp._user_access_token()))
    except Exception as exc:
        _check("refresh endpoint reachable", False, repr(exc))


def layer7_create_playlist_dry(token: str | None) -> None:
    print("\n=== Layer 7: create_playlist end-to-end (confirm gate first) ===")
    res = sp.create_playlist("MoodOS audit probe", ["spotify:track:0"], confirm=False)
    print(f"  confirm=False -> {json.dumps(res)}")
    _check("confirm=False aborts without calling Spotify",
           res.get("executed") is False and res.get("status") == "aborted")
    _check("aborted result has a user message", bool(res.get("message")))

    # prepare (confirm=True) is the layer that would really create a playlist.
    # Only run it when the connection is actually capable, and use an empty URI
    # list so nothing lands in the user's library.
    if sp.can_create_playlists():
        print("  connected with playlist scopes -- skipping the real create "
              "(this script never writes to the user's account)")
    else:
        res2 = sp.create_playlist("MoodOS audit probe", [], confirm=True)
        print(f"  confirm=True without scopes -> {json.dumps(res2)}")
        _check("unscoped create fails before calling Spotify with a clear status",
               res2.get("executed") is False and res2.get("status") in
               ("needs_auth", "create_failed", "auth_failed"))
        _check("failed result carries a user message", bool(res2.get("message")))
        _check("failed result carries an action the UI can branch on",
               bool(res2.get("action")))

    for status in ("prepared", "aborted", "needs_auth", "auth_failed",
                   "create_failed", "error", "executed"):
        _check(f"USER_MESSAGES has copy for {status}", status in sp.USER_MESSAGES)
        _check(f"copy for {status} has message+action",
               bool(sp.USER_MESSAGES[status].get("message"))
               and bool(sp.USER_MESSAGES[status].get("action")))


def main() -> int:
    print(f"spotify.py at {Path(sp.__file__).resolve()}")
    print(f"TOKEN_PATH   = {sp.TOKEN_PATH}")
    print(f"exists       = {sp.TOKEN_PATH.exists()}  mtime="
          f"{time.ctime(sp.TOKEN_PATH.stat().st_mtime) if sp.TOKEN_PATH.exists() else '-'}")
    ok = layer1_config()
    token = layer2_app_token() if ok else None
    layer3_search(token)
    layer4_oauth_redirect(token)
    layer5_scopes()
    layer6_refresh(token)
    layer7_create_playlist_dry(token)

    print("\n" + "=" * 60)
    if _failures:
        print(f"{len(_failures)} FAILED:")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("ALL SPOTIFY LAYERS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
