"""A4: 6h result cache + 24h stale copy for the two location lookups."""

import time

import pytest

from moodos.cache import ttl_cache
from moodos.location_service import location_service
from moodos import providers


def _key(lat, lon, cat, radius):
    return f"poi:{round(lat, 3)}:{round(lon, 3)}:{cat}:{radius}"


def test_find_nearby_places_second_call_is_cached():
    lat, lon = 28.6139, 77.2090
    for k in [k for k in list(ttl_cache._data) if k.startswith("poi:")]:
        ttl_cache._data.pop(k, None)
    calls = {"n": 0}

    def fake_overpass(*a, **k):
        calls["n"] += 1
        return [{"type": "node", "id": 1, "lat": lat, "lon": lon,
                 "tags": {"name": "Scoop N Munch", "amenity": "cafe"}}]

    real = location_service._overpass_elements
    location_service._overpass_elements = fake_overpass
    try:
        t0 = time.perf_counter()
        first = location_service.search_nearby_places(lat, lon, categories="cafe")
        t_first = time.perf_counter() - t0
        t0 = time.perf_counter()
        second = location_service.search_nearby_places(lat, lon, categories="cafe")
        t_second = time.perf_counter() - t0
    finally:
        location_service._overpass_elements = real

    assert calls["n"] == 1, calls
    assert [p["title"] for p in first] == ["Scoop N Munch"]
    assert [p["title"] for p in second] == ["Scoop N Munch"]
    print(f"first={t_first:.3f}s second={t_second:.3f}s")
    assert t_second < 0.5, t_second


def test_nearby_restaurants_second_call_is_cached(monkeypatch):
    lat, lon = 28.6139, 77.2090
    for k in [k for k in list(ttl_cache._data) if k.startswith("rest:")]:
        ttl_cache._data.pop(k, None)
    calls = {"n": 0}

    def fake_query(q):
        calls["n"] += 1
        return {"elements": [{"type": "node", "id": 2, "lat": lat, "lon": lon,
                              "tags": {"name": "Saganwala Restaurant",
                                       "amenity": "restaurant",
                                       "cuisine": "indian"}}]}

    monkeypatch.setattr(providers, "_overpass_query", fake_query)
    t0 = time.perf_counter()
    first = providers.nearby_restaurants(lat, lon, limit=5)
    t_first = time.perf_counter() - t0
    t0 = time.perf_counter()
    second = providers.nearby_restaurants(lat, lon, limit=5)
    t_second = time.perf_counter() - t0

    assert calls["n"] == 1, calls
    assert [p["title"] for p in first] == ["Saganwala Restaurant"]
    assert [p["title"] for p in second] == ["Saganwala Restaurant"]
    print(f"first={t_first:.3f}s second={t_second:.3f}s")
    assert t_second < 0.5, t_second


def test_stale_copy_served_when_everything_fails(monkeypatch):
    lat, lon = 28.6139, 77.2090
    cat = "cafe"
    key = _key(lat, lon, cat, 4000)
    stale_key = key + ":stale"

    def boom(*a, **k):
        return None  # same contract as the real _overpass_elements on failure

    ttl_cache._data.pop(key, None)
    ttl_cache._data.pop(stale_key, None)
    monkeypatch.setattr(location_service, "_overpass_elements", boom)
    monkeypatch.setattr("moodos.location_service.fallback_places", lambda *a, **k: [])
    monkeypatch.setattr("moodos.fallback_places.fallback_places", lambda *a, **k: [])
    with pytest.raises(Exception):
        location_service.search_nearby_places(lat, lon, categories=cat, strict=True)
    assert key not in ttl_cache._data

    # A successful run plants the 24h stale copy...
    ttl_cache.set(key, [{"title": "Scoop N Munch", "category": cat}], ttl_seconds=6 * 3600)
    ttl_cache.set(stale_key, [{"title": "Scoop N Munch", "category": cat}], ttl_seconds=24 * 3600)
    # ...then the 6h copy expires while the stale one survives.
    ttl_cache._data[key]["expires"] = time.time() - 1
    ttl_cache._data[stale_key]["expires"] = time.time() + 24 * 3600

    out = location_service.search_nearby_places(lat, lon, categories=cat)
    assert [p["title"] for p in out] == ["Scoop N Munch"]
