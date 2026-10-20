"""G1: institutional filter on fallback results + shorter TTL for fallback-sourced data."""

import time

from moodos.cache import ttl_cache
from moodos.location_service import location_service
from moodos import providers


def _clear(prefix):
    for k in [k for k in list(ttl_cache._data) if k.startswith(prefix)]:
        ttl_cache._data.pop(k, None)


def _fb_place(title, source="nominatim", cat="restaurant"):
    return {
        "id": f"osm:{title}",
        "title": title,
        "kind": "food",
        "subtype": "restaurant",
        "category": cat,
        "lat": 28.6139,
        "lon": 77.2090,
        "text": title,
        "opening_hours": None,
        "opening_note": "opening hours not listed",
        "source": source,
        "estimated_cost": 250,
        "price_tier": "mid",
        "price_is_estimate": True,
        "duration_min": 60,
        "intensity": "low",
        "crowded": False,
        "outdoor": False,
        "review_quality": 7.0,
        "has_venue": True,
        "distance_km": 0.5,
    }


def test_restaurants_fallback_drops_institutional_names(monkeypatch):
    lat, lon = 28.6139, 77.2090
    _clear("restaurants:")
    fake = [_fb_place("Law Canteen(F2)"), _fb_place("Pharma Canteen(F1)"),
            _fb_place("Saganwala Restaurant")]

    monkeypatch.setattr(providers, "_overpass_query", lambda q: None)
    monkeypatch.setattr("moodos.fallback_places.fallback_places",
                        lambda *a, **k: [dict(p) for p in fake])
    out = providers.nearby_restaurants(lat, lon, limit=10)
    titles = [p["title"] for p in out]
    assert titles == ["Saganwala Restaurant"], titles


def test_search_nearby_places_fallback_drops_institutional_names(monkeypatch):
    lat, lon = 28.6139, 77.2090
    _clear("poi:")
    fake = [_fb_place("Law Canteen(F2)", cat="cafe"), _fb_place("Saganwala Restaurant", cat="cafe")]
    monkeypatch.setattr(location_service, "_overpass_elements", lambda *a, **k: None)
    monkeypatch.setattr("moodos.location_service.fallback_places",
                        lambda *a, **k: [dict(p) for p in fake])
    out = location_service.search_nearby_places(lat, lon, categories="cafe")
    titles = [p["title"] for p in out]
    assert titles == ["Saganwala Restaurant"], titles


def test_fallback_sourced_result_cached_30m_not_6h(monkeypatch):
    lat, lon = 28.6139, 77.2090
    _clear("restaurants:")
    fake = [_fb_place("Saganwala Restaurant")]
    monkeypatch.setattr(providers, "_overpass_query", lambda q: None)
    monkeypatch.setattr("moodos.fallback_places.fallback_places",
                        lambda *a, **k: [dict(p) for p in fake])
    providers.nearby_restaurants(lat, lon, limit=5)
    key = f"restaurants:{round(lat, 3)}:{round(lon, 3)}:::{5000}"
    left = ttl_cache._data[key]["expires"] - time.time()
    assert left <= 1800, left
    assert left > 1700, left


def test_overpass_sourced_result_keeps_6h(monkeypatch):
    lat, lon = 28.6139, 77.2090
    _clear("restaurants:")
    row = {"type": "node", "id": 9, "lat": lat, "lon": lon,
           "tags": {"name": "Saganwala Restaurant", "amenity": "restaurant",
                    "cuisine": "indian"}}
    monkeypatch.setattr(providers, "_overpass_query", lambda q: {"elements": [row]})
    providers.nearby_restaurants(lat, lon, limit=5)
    key = f"restaurants:{round(lat, 3)}:{round(lon, 3)}:::{5000}"
    left = ttl_cache._data[key]["expires"] - time.time()
    assert left > 6 * 3600 - 60, left


def test_search_nearby_places_fallback_sourced_ttl(monkeypatch):
    lat, lon = 28.6139, 77.2090
    _clear("poi:")
    fake = [_fb_place("Saganwala Restaurant", cat="cafe")]
    monkeypatch.setattr(location_service, "_overpass_elements", lambda *a, **k: None)
    monkeypatch.setattr("moodos.location_service.fallback_places",
                        lambda *a, **k: [dict(p) for p in fake])
    location_service.search_nearby_places(lat, lon, categories="cafe")
    key = f"poi:{round(lat, 3)}:{round(lon, 3)}:cafe:{4000}"
    left = ttl_cache._data[key]["expires"] - time.time()
    assert left <= 1800, left
