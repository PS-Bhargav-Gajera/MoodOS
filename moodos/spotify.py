"""Spotify Web API provider (search via app credentials; playlists via user OAuth)."""

from __future__ import annotations

import base64
import json
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from moodos.config import DATA_DIR, settings

log = logging.getLogger("moodos.spotify")
TOKEN_PATH = DATA_DIR / "spotify_tokens.json"
SCOPES = "playlist-modify-private playlist-modify-public user-read-email"
TIMEOUT = 15.0

_app_token: dict[str, Any] = {"access": "", "expires": 0.0}
_oauth_state = ""


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


def search_tracks(query: str, limit: int = 8, market: str = "IN", offset: int = 0) -> list[dict]:
    token = app_access_token()
    if not token:
        return []
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.get(
                "https://api.spotify.com/v1/search",
                headers={"Authorization": f"Bearer {token}"},
                params={"q": query, "type": "track", "limit": limit, "market": market, "offset": offset},
            )
        if r.status_code >= 400:
            log.warning("Spotify search failed: %s", r.status_code)
            return []
        items = []
        for row in (r.json().get("tracks") or {}).get("items") or []:
            artists = ", ".join(a.get("name", "") for a in row.get("artists") or [])
            duration_ms = row.get("duration_ms") or 0
            items.append(
                {
                    "id": f"spotify:{row.get('id')}",
                    "uri": row.get("uri"),
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
        return items
    except Exception as exc:
        log.warning("Spotify search error: %s", exc)
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
            log.warning("Spotify auth code exchange failed: %s", r.status_code)
            return {"ok": False, "error": "exchange_failed"}
        data = r.json()
        _save_user(
            {
                "access_token": data.get("access_token"),
                "refresh_token": data.get("refresh_token"),
                "expires": time.time() + int(data.get("expires_in") or 3600),
            }
        )
        return {"ok": True}
    except Exception as exc:
        log.warning("Spotify exchange error: %s", exc)
        return {"ok": False, "error": "exchange_error"}


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
            return None
        body = r.json()
        data["access_token"] = body.get("access_token")
        data["expires"] = time.time() + int(body.get("expires_in") or 3600)
        if body.get("refresh_token"):
            data["refresh_token"] = body["refresh_token"]
        _save_user(data)
        return data["access_token"]
    except Exception:
        return None


def create_playlist(name: str, track_uris: list[str], confirm: bool) -> dict[str, Any]:
    if not confirm:
        return {"status": "aborted", "executed": False}
    token = _user_access_token()
    if not token:
        return {
            "status": "needs_auth",
            "executed": False,
            "authorize_url": authorize_url(),
            "note": "Connect the Spotify account that owns the moodoss app (Development mode).",
        }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            me = client.get("https://api.spotify.com/v1/me", headers=headers)
            if me.status_code >= 400:
                return {"status": "auth_failed", "executed": False}
            user_id = me.json().get("id")
            created = client.post(
                f"https://api.spotify.com/v1/users/{user_id}/playlists",
                headers=headers,
                json={"name": name, "public": False, "description": "MoodOS calming evening playlist"},
            )
            if created.status_code >= 400:
                return {"status": "create_failed", "executed": False}
            playlist = created.json()
            uris = [u for u in track_uris if u]
            if uris:
                client.post(
                    f"https://api.spotify.com/v1/playlists/{playlist.get('id')}/tracks",
                    headers=headers,
                    json={"uris": uris[:50]},
                )
        return {
            "status": "executed",
            "executed": True,
            "provider": "Spotify",
            "playlist_url": (playlist.get("external_urls") or {}).get("spotify"),
            "playlist_id": playlist.get("id"),
        }
    except Exception as exc:
        log.warning("Spotify playlist error: %s", exc)
        return {"status": "error", "executed": False}
