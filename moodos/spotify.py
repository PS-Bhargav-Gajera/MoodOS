"""Spotify Web API provider (search via app credentials; playlists via user OAuth)."""

from __future__ import annotations

import base64
import json
import logging
import re
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from moodos.config import DATA_DIR, settings

log = logging.getLogger("moodos.spotify")
TOKEN_PATH = DATA_DIR / "spotify_tokens.json"
SCOPES = (
    "playlist-modify-private playlist-modify-public user-read-email "
    "user-read-private user-top-read"
)
# The subset of SCOPES that create_playlist cannot work without. Compared
# against the grant actually stored in TOKEN_PATH — see scope_gap().
CREATE_SCOPES = ("playlist-modify-private", "playlist-modify-public")
TIMEOUT = 15.0

# User-facing copy for every status this module (and mcp_server.create_playlist)
# can return. The client renders `message` and branches on `action`; the raw
# status string and any Spotify error detail stay in the log.
#
# Every literal `status` value returned by spotify.py and mcp_server.py must
# appear here — test_every_playlist_status_has_a_message enforces that, so a
# new code cannot ship without user-facing copy.
USER_MESSAGES: dict[str, dict[str, str]] = {
    "prepared": {
        "message": "Here's a playlist picked for your mood — confirm to create it on Spotify.",
        "action": "confirm",
    },
    "aborted": {
        "message": "Playlist creation was cancelled. Nothing was added to your Spotify account.",
        "action": "none",
    },
    "needs_auth": {
        "message": "Connect your Spotify account to create this playlist.",
        "action": "connect",
    },
    "auth_failed": {
        "message": "Your Spotify session has expired. Reconnect to continue.",
        "action": "reconnect",
    },
    "create_failed": {
        "message": "Spotify couldn't create the playlist. Your tracks are still here — try again.",
        "action": "retry",
    },
    "error": {
        "message": "Couldn't reach Spotify. Check your connection and try again.",
        "action": "retry",
    },
    "executed": {
        "message": "Playlist created on Spotify.",
        "action": "open",
    },
}

# create_failed is the one status that is really several different problems;
# the HTTP status is what tells them apart.
_CREATE_FAILURES: dict[int, dict[str, str]] = {
    401: {
        "message": "Your Spotify session has expired. Reconnect to continue.",
        "action": "reconnect",
    },
    403: {
        "message": (
            "Spotify declined to create the playlist — this connection is missing "
            "playlist permission. Reconnect to grant it."
        ),
        "action": "reconnect",
    },
    429: {
        "message": "Too many playlist requests just now. Try again in a minute.",
        "action": "retry",
    },
}

_app_token: dict[str, Any] = {"access": "", "expires": 0.0}
_oauth_state = ""


def friendly(status: str, message: str | None = None, action: str | None = None) -> dict[str, Any]:
    """Build the user-facing part of a result dict.

    `status` is the machine-readable code and stays in the payload for API
    consumers; `message` is the only field the UI should render, and `action`
    is what it branches on to offer a way forward.
    """
    entry = USER_MESSAGES.get(status, USER_MESSAGES["error"])
    return {
        "status": status,
        "message": message or entry["message"],
        "action": action or entry["action"],
    }


def _create_failure(status_code: int) -> dict[str, Any]:
    """Map a failed playlist-creation HTTP status onto user-facing copy."""
    entry = _CREATE_FAILURES.get(status_code, USER_MESSAGES["create_failed"])
    return friendly("create_failed", message=entry["message"], action=entry["action"])


def _error_detail(resp: Any) -> str:
    """Pull a short, human-readable reason out of a Spotify error response.

    Log-only. Spotify names the cause inconsistently across endpoints — it may
    send `error.reason`, `error.message`, or a bare string — so check all three.
    """
    try:
        body = resp.json()
    except Exception:
        body = None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            parts = [str(err[k]) for k in ("reason", "message") if err.get(k)]
            if parts:
                return " / ".join(parts)
            return f"error={err}"
        if err:
            return str(err)
    text = " ".join(str(getattr(resp, "text", "") or "").split())
    return text[:200] or "<empty body>"


def _log_spotify_failure(op: str, resp: Any, context: str = "") -> None:
    """Log the status and reason of a failed Spotify call. Never returned."""
    log.warning(
        "spotify %s failed: status=%s reason=%s%s",
        op,
        getattr(resp, "status_code", "?"),
        _error_detail(resp),
        f" {context}" if context else "",
    )



def configured() -> bool:
    return bool(settings.spotify_client_id and settings.spotify_client_secret)


def _basic_auth() -> str:
    raw = f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def app_access_token() -> str | None:
    if not configured():
        return None
    if _app_token["access"] and _app_token["expires"] > time.time() + 30:
        return _app_token["access"]
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(
                "https://accounts.spotify.com/api/token",
                headers={
                    "Authorization": _basic_auth(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials"},
            )
        if r.status_code >= 400:
            log.warning("Spotify client-credentials failed: %s", r.status_code)
            return None
        data = r.json()
        _app_token["access"] = data["access_token"]
        _app_token["expires"] = time.time() + int(data.get("expires_in") or 3600)
        return _app_token["access"]
    except Exception as exc:
        log.warning("Spotify token error: %s", exc)
        return None


def _search_with_token(token: str, query: str, limit: int, market: str, offset: int) -> tuple[int, list[dict]]:
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.get(
            "https://api.spotify.com/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": query, "type": "track", "limit": limit, "market": market, "offset": offset},
        )
    if r.status_code >= 400:
        return r.status_code, []
    items = []
    for row in (r.json().get("tracks") or {}).get("items") or []:
        artists = ", ".join(a.get("name", "") for a in row.get("artists") or [])
        duration_ms = row.get("duration_ms") or 0
        items.append(
            {
                "id": f"spotify:{row.get('id')}",
                "uri": row.get("uri"),
                "name": row.get("name"),
                "artist": artists,
                "title": f"{row.get('name')} — {artists}",
                "kind": "music",
                "text": f"{row.get('album', {}).get('name', '')} {artists}",
                "preview_url": row.get("preview_url"),
                "url": (row.get("external_urls") or {}).get("spotify"),
                "source": "spotify",
                "estimated_cost": 0,
                "duration_min": round(duration_ms / 60000, 1) if duration_ms else 0,
                "duration_sec": duration_ms // 1000 if duration_ms else 0,
                "intensity": "low",
            }
        )
    return r.status_code, items


def _track_key(track: dict) -> str:
    """Identity used for de-duplication: song title + artist, case/punctuation
    insensitive.

    Deliberately NOT the Spotify id: the same song appears under several ids
    (different album, live/remix/stereo variants), which is how the identical
    track ended up twice in one playlist.
    """
    name = str(track.get("name") or track.get("title") or "").split(" — ")[0]
    artist = str(track.get("artist") or "")
    if not artist and track.get("title"):
        # title is "name — artists"; recover the artist half if name is absent
        parts = str(track.get("title")).split(" — ", 1)
        if len(parts) == 2:
            name, artist = parts[0], parts[1]
    key = f"{re.sub(r'[^a-z0-9]+', ' ', name.lower()).strip()}|" \
          f"{re.sub(r'[^a-z0-9]+', ' ', artist.lower()).strip()}"
    return key


def _dedupe_tracks(tracks: list[dict]) -> list[dict]:
    """Drop repeated songs, keeping first occurrence and its order."""
    seen: set[str] = set()
    unique: list[dict] = []
    for t in tracks:
        key = _track_key(t)
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    if len(unique) != len(tracks):
        log.info("spotify dedupe: %s -> %s tracks", len(tracks), len(unique))
    return unique


def search_tracks(query: str, limit: int = 8, market: str = "IN", offset: int = 0) -> list[dict]:
    """Live Spotify search. Prefers the connected user token (Premium), then
    the app client-credentials token."""
    # Spotify rejects track searches with limit > 10 (HTTP 400 "Invalid limit"),
    # so clamp instead of letting the whole music leg fail.
    limit = max(1, min(int(limit or 8), 10))
    tokens = [t for t in (_user_access_token(), app_access_token()) if t]
    seen: set[str] = set()
    unique = []
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        unique.append(t)
    try:
        last_status = 0
        for token in unique:
            status, items = _search_with_token(token, query, limit, market, offset)
            last_status = status
            if items:
                return _dedupe_tracks(items)
            if status == 403:
                log.warning("spotify search 403 with a credential; trying next: %s", query)
                continue
            if status >= 400:
                log.warning("spotify search failed: status=%s query=%s", status, query)
        if last_status:
            log.warning("spotify search empty: last status=%s query=%s", last_status, query)
        return []
    except Exception as exc:
        log.warning("spotify search error: %s", exc)
        return []


def _load_user() -> dict:
    if TOKEN_PATH.exists():
        try:
            return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_user(data: dict) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(data), encoding="utf-8")


def user_connected() -> bool:
    return bool(_load_user().get("refresh_token") or _load_user().get("access_token"))


def granted_scopes() -> set[str]:
    """Scopes actually attached to the stored refresh token.

    Empty when the token file predates scope tracking (or the grant has been
    revoked), which callers must treat as "unknown", never as "has none".
    """
    return {s for s in str(_load_user().get("scope") or "").split() if s}


def scope_gap() -> list[str]:
    """Playlist-write scopes we need that the stored grant does not carry.

    OAuth scopes are immutable per grant: refreshing a token can never widen
    it, only a fresh re-consent can. Returning a non-empty list means the user
    must hit /spotify/login again before create_playlist can ever succeed.
    """
    granted = granted_scopes()
    if not granted:
        return []  # unknown — don't guess and don't block
    return [s for s in CREATE_SCOPES if s not in granted]


def can_create_playlists() -> bool:
    """Whether the stored connection is actually usable for playlist writes.

    Stricter than user_connected(): a token that predates the playlist scopes
    is connected but cannot do the job, and reporting it as connected is what
    made a guaranteed-to-fail create look like an arbitrary Spotify outage.
    """
    return user_connected() and not scope_gap()


def authorize_url() -> str:
    global _oauth_state
    _oauth_state = secrets.token_urlsafe(16)
    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings.spotify_redirect_uri,
        "scope": SCOPES,
        "state": _oauth_state,
        "show_dialog": "false",
    }
    return "https://accounts.spotify.com/authorize?" + urlencode(params)


def exchange_code(code: str, state: str) -> dict[str, Any]:
    global _oauth_state
    if not state or state != _oauth_state:
        return {"ok": False, "error": "invalid_state"}
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(
                "https://accounts.spotify.com/api/token",
                headers={
                    "Authorization": _basic_auth(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.spotify_redirect_uri,
                },
            )
        if r.status_code >= 400:
            log.warning("Spotify auth code exchange failed: %s reason=%s",
                        r.status_code, _error_detail(r))
            return {"ok": False, "error": "exchange_failed"}
        data = r.json()
        _save_user(_token_record(data))
        return {"ok": True}
    except Exception as exc:
        log.warning("Spotify exchange error: %s", exc)
        return {"ok": False, "error": "exchange_error"}


def _token_record(body: dict) -> dict[str, Any]:
    """Build the token file record from a Spotify token response.

    Stores the `scope` the grant actually carries, not the scopes we asked for:
    Spotify omits the field when it matches the request, and a grant that came
    back narrower than requested is exactly the case that is otherwise
    invisible until a write endpoint returns a bare 403.
    """
    return {
        "access_token": body.get("access_token"),
        "refresh_token": body.get("refresh_token"),
        "expires": time.time() + int(body.get("expires_in") or 3600),
        "scope": body.get("scope") or " ".join(SCOPES.split()),
    }


def _user_access_token() -> str | None:
    data = _load_user()
    if not data:
        return None
    if data.get("access_token") and float(data.get("expires") or 0) > time.time() + 30:
        return data["access_token"]
    refresh = data.get("refresh_token")
    if not refresh:
        return None
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(
                "https://accounts.spotify.com/api/token",
                headers={
                    "Authorization": _basic_auth(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "refresh_token", "refresh_token": refresh},
            )
        if r.status_code >= 400:
            log.warning("spotify token refresh failed: status=%s reason=%s",
                        r.status_code, _error_detail(r))
            return None
        body = r.json()
        data["access_token"] = body.get("access_token")
        data["expires"] = time.time() + int(body.get("expires_in") or 3600)
        if body.get("refresh_token"):
            data["refresh_token"] = body["refresh_token"]
        # A refresh can never widen the grant, but Spotify may restate it.
        # Keep the recorded scope in sync so scope_gap() stays truthful.
        if body.get("scope"):
            data["scope"] = body["scope"]
        _save_user(data)
        return data["access_token"]
    except Exception as exc:
        log.warning("spotify token refresh error: %s", exc)
        return None


def create_playlist(name: str, track_uris: list[str], confirm: bool) -> dict[str, Any]:
    if not confirm:
        return {**friendly("aborted"), "executed": False}
    uris = [u for u in track_uris if u]
    if not uris:
        # Never create an empty playlist on the user's account: the tracks we
        # prepared are the whole point, and an empty shell is worse than none.
        log.warning("spotify create_playlist refused: 0 track uris for %r", name)
        return {
            **friendly(
                "create_failed",
                message=(
                    "There were no tracks to add, so no playlist was created. "
                    "Try again in a moment."
                ),
                action="retry",
            ),
            "executed": False,
        }
    token = _user_access_token()
    if not token:
        return {
            **friendly("needs_auth"),
            "executed": False,
            "authorize_url": authorize_url(),
        }
    gap = scope_gap()
    if gap:
        # Don't call Spotify at all: no grant can ever be widened by refreshing,
        # so this is guaranteed to fail. Only a fresh re-consent fixes it.
        log.warning(
            "spotify scope_mismatch: stored grant is missing %s; "
            "user must re-consent via /spotify/login",
            ", ".join(gap),
        )
        return {
            **friendly(
                "create_failed",
                message=(
                    "Spotify wouldn't create the playlist because this connection "
                    "was granted before playlist permission was requested. "
                    "Reconnect to grant it."
                ),
                action="reconnect",
            ),
            "executed": False,
            "scope_gap": gap,
        }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            me = client.get("https://api.spotify.com/v1/me", headers=headers)
            if me.status_code >= 400:
                _log_spotify_failure("GET /v1/me", me)
                return {**friendly("auth_failed"), "executed": False}
            profile = me.json()
            user_id = profile.get("id")
            # `product` is the field that settles "is this account Premium?"
            # questions, which a bare 403 otherwise leaves entirely open.
            log.info(
                "spotify playlist create: user=%s product=%s scopes=%s",
                user_id,
                profile.get("product"),
                " ".join(sorted(granted_scopes())) or "unknown",
            )
            created = client.post(
                f"https://api.spotify.com/v1/users/{user_id}/playlists",
                headers=headers,
                json={"name": name, "public": False, "description": "MoodOS calming evening playlist"},
            )
            if created.status_code >= 400:
                _log_spotify_failure(
                    "POST /v1/users/{id}/playlists",
                    created,
                    context=f"user={user_id} product={profile.get('product')}",
                )
                return {**_create_failure(created.status_code), "executed": False}
            playlist = created.json()
            # Spotify caps a single add-tracks call at 100 URIs. Anything past
            # that is dropped rather than silently half-added, and the count we
            # actually sent is reported back so the caller can see the gap.
            sent = uris[:100]
            added = client.post(
                f"https://api.spotify.com/v1/playlists/{playlist.get('id')}/tracks",
                headers=headers,
                json={"uris": sent},
            )
            # The playlist exists either way, so this stays non-fatal — but
            # silently landing an empty playlist is a bug worth seeing.
            if added.status_code >= 400:
                _log_spotify_failure(
                    "POST /v1/playlists/{id}/tracks",
                    added,
                    context=f"playlist={playlist.get('id')} uris={len(sent)}",
                )
        return {
            **friendly("executed"),
            "executed": True,
            "provider": "Spotify",
            "playlist_url": (playlist.get("external_urls") or {}).get("spotify"),
            "playlist_id": playlist.get("id"),
            "tracks_added": len(sent),
            "tracks_requested": len(uris),
        }
    except Exception as exc:
        log.warning("spotify playlist error: %s", exc, exc_info=True)
        return {**friendly("error"), "executed": False}
