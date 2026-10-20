"""D1: duplicate places removed at the data layer."""

import pytest

from moodos import fallback_places as fb
from moodos import orchestrator as orch
from moodos import providers


def _place(name, lat, lon, source_id, **kw):
    p = {
        "id": f"nominatim:{source_id}",
        "source_id": source_id,
        "title": name,
        "name": name,
        "lat": lat,
        "lon": lon,
        "category": "restaurant",
        "subtype": "restaurant",
        "kind": "food",
        "source": "nominatim",
        "duration_min": 60,
        "estimated_cost": 250,
        "intensity": "low",
        "outdoor": False,
        "review_quality": 7.0,
        "moods": ["happy"],
    }
    p.update(kw)
    return p


def test_fallback_places_dedupes_same_id_and_nearby_name():
    # Same id twice, plus the same canteen ~25 m away under a slightly
    # different name spelling -> 2 real places, not 4.
    rows = [
        {"source_id": "F2", "name": "Law Canteen(F2)", "lat": 28.61390, "lon": 77.20900},
        {"source_id": "F2", "name": "Law Canteen(F2)", "lat": 28.61390, "lon": 77.20900},
        {"source_id": "F1", "name": "Pharma Canteen(F1)", "lat": 28.61410, "lon": 77.20900},
        {"source_id": "F9", "name": "Pharma Canteen (F1)", "lat": 28.61412, "lon": 77.20902},
    ]
    spec = fb._SPECS["restaurant"]
    raw = [fb._to_place(r, spec, "nominatim", 28.6139, 77.209) for r in rows]
    out = fb._dedupe_places(raw)
    titles = sorted(p["title"] for p in out)
    assert titles == ["Law Canteen(F2)", "Pharma Canteen(F1)"], titles


def test_nearby_restaurants_dedupes_fallback_list(monkeypatch):
    rows = [
        {"source_id": "F2", "name": "Law Canteen(F2)", "lat": 28.61390, "lon": 77.20900},
        {"source_id": "F2", "name": "Law Canteen(F2)", "lat": 28.61390, "lon": 77.20900},
        {"source_id": "F1", "name": "Pharma Canteen(F1)", "lat": 28.61410, "lon": 77.20900},
        {"source_id": "F9", "name": "Pharma Canteen (F1)", "lat": 28.61412, "lon": 77.20902},
    ]
    monkeypatch.setattr(fb, "_env_key_names", lambda: set())
    monkeypatch.setattr(fb, "_nominatim_search", lambda *a, **k: list(rows))
    monkeypatch.setattr(providers, "_overpass_query", lambda q: None)

    out = providers.nearby_restaurants(28.6139, 77.209, limit=10)
    titles = sorted(p["title"] for p in out)
    assert titles == ["Law Canteen(F2)", "Pharma Canteen(F1)"], titles


def test_pool_dedupes_same_venue_from_places_and_restaurants():
    # The same canteen arrives from both find_nearby_places (kind=food) and
    # search_restaurants (kind=food, different id/source). It must survive
    # into the pool exactly once.
    from_canteen = _place("Law Canteen", 28.61390, 77.20900, "F2")
    from_places = dict(from_canteen, id="osm:node:12345", source="overpass",
                       phone=None, website=None, address=None, opening_hours=None)
    pool = orch._dedupe_pool([from_places, from_canteen])
    assert len(pool) == 1
    titles = [p["title"] for p in pool]
    assert titles == ["Law Canteen"]


def test_pool_dedupe_prefers_higher_score():
    low = _place("Law Canteen", 28.61390, 77.20900, "F2", final_score=0.2)
    high = dict(_place("Law Canteen", 28.61390, 77.20900, "F2", final_score=0.9),
                address="Sector 14, hostels")
    pool = orch._dedupe_pool([low, high])
    assert len(pool) == 1
    assert pool[0]["final_score"] == 0.9
    assert pool[0]["address"] == "Sector 14, hostels"
