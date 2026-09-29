"""Global test defaults: keep tests hermetic and fast.

The LocationService is the only module that talks to OSM-family public APIs.
Under pytest we stub its transport so routing falls back to estimates, POI
search returns empty, and the suite never depends on (or is slowed by) the
network. Individual tests that want to exercise the service override the
service methods directly.
"""

import pytest

from moodos.cache import ttl_cache
from moodos.location_service import location_service


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
