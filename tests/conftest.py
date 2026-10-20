"""Global test defaults: keep tests hermetic and fast.

Network: a module-level guard on httpx.Client.send blocks every real HTTP
call (any client whose transport is httpx.HTTPTransport) — this covers
providers, Spotify, Mem0, location, and the Groq/Gemini SDKs, which all
speak httpx. In-process transports (TestClient's ASGITransport, the
MockTransport/fake-client patterns used by individual tests) pass through.
Individual tests that want to exercise a service override the service
methods or replace httpx.Client entirely with a fake.

Storage: settings.sqlite_path / settings.cache_path and spotify.TOKEN_PATH
are redirected to a temp dir so tests never touch data/*.db, the real TTL
cache, or the developer's live Spotify session.
"""

import tempfile
from pathlib import Path

import httpx
import pytest

# --- Network guard: install BEFORE any moodos import ---------------------
# moodos.memory pings api.mem0.ai at import time (Mem0Cloud._ping); the
# guard makes that fail fast instead of waiting on a real socket.
_REAL_HTTPX_SEND = httpx.Client.send


def _guarded_send(self, request, *args, **kwargs):
    if isinstance(self._transport, httpx.HTTPTransport):
        raise RuntimeError("network disabled in tests")
    return _REAL_HTTPX_SEND(self, request, *args, **kwargs)


httpx.Client.send = _guarded_send

# -------------------------------------------------------------------------

from moodos.cache import ttl_cache
from moodos.config import settings
from moodos.db import init_db
from moodos.location_service import location_service
from moodos import spotify as spotify_api

# Tests must not touch the developer's real data/*.db. conftest is imported
# before any test module, so redirecting settings.sqlite_path here also covers
# the module-level init_db() calls in test_journal.py and test_preferences.py.
# db._connect() reads settings.sqlite_path on every connection, so mutating the
# instance attribute redirects every caller.
#
# spotify.TOKEN_PATH gets the same treatment: _save_user() writes the real file
# unconditionally, so a test that exercises the OAuth exchange or the
# scope-mismatch path would otherwise overwrite the developer's live Spotify
# session and force a re-login.
#
# cache_path likewise: the autouse fixture below snapshots/restores the TTL
# cache and writes it back — pointed at temp, those writes stay out of
# data/ttl_cache.json.
_TMP_DATA = Path(tempfile.mkdtemp(prefix="moodos_pytest_"))
settings.sqlite_path = _TMP_DATA / "moodos.db"
settings.cache_path = _TMP_DATA / "ttl_cache.json"
spotify_api.TOKEN_PATH = _TMP_DATA / "spotify_tokens.json"
init_db()


@pytest.fixture(autouse=True)
def _reset_overpass_breaker():
    """The Overpass circuit breaker is a module-level singleton, like the TTL
    cache. Without a reset, one test that exhausts the Overpass budget would
    open the breaker and make every later test silently skip OSM."""
    from moodos import providers as providers_api

    providers_api.reset_overpass_breaker()
    yield
    providers_api.reset_overpass_breaker()


@pytest.fixture(autouse=True)
def _offline_osm(monkeypatch):
    def _offline(*_args, **_kwargs):
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(location_service, "_http_get_json", _offline)
    monkeypatch.setattr(location_service, "_http_post_json", _offline)
    # Keep OSRM "enabled" so the fallback path inside calculate_route runs.
    monkeypatch.setattr(location_service, "osrm_enabled", True)

    # The TTL cache is a module-level singleton backed by a JSON file, so
    # results from a previous run would leak in and make "the transport was
    # called exactly once" assertions depend on disk state. Snapshot it and
    # start every test from an empty cache.
    saved = dict(ttl_cache._data)
    ttl_cache._data = {}
    ttl_cache._save()
    yield
    ttl_cache._data = saved
    ttl_cache._save()
    location_service.osrm_enabled = True
    location_service._fail_counts.clear()
