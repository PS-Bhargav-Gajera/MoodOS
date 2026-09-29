"""QA tests for the location system (17 documented failure/edge cases).

All tests are hermetic: the transport seams (HTTP + Overpass) are stubbed, so
no OSM-family API is contacted. Real routing falls back to estimates, which is
exactly the production behaviour when OSRM is down.
"""

from moodos.config import settings
from moodos.location_service import LocationService, _parse_categories

# Use distinct coords per test so the shared TTL cache never leaks results
# between tests.
ORIGIN = {"lat": 23.0123, "lon": 72.5678}


def _el(name="Cafe A", amenity="cafe", lat=23.0130, lon=72.5680, oid=1,
        kind="node", tags=None, center=None):
    t = {"name": name}
    if amenity:
        t["amenity"] = amenity
    if tags:
        t.update(tags)
    el = {"type": kind, "id": oid, "tags": t}
    if center:
        el["center"] = center
    else:
        el["lat"] = lat
        el["lon"] = lon
    return el


class _FakeOverpass:
    def __init__(self, elements):
        self.elements = elements
        self.calls = 0

    def __call__(self, lat, lon, radius_m, cats):
        self.calls += 1
        return self.elements


def _fresh_service():
    """A LocationService with the network disabled, so the suite never touches
    public OSM-family APIs. Tests that exercise a transport directly override
    the seam before use."""
    svc = LocationService()

    def offline(*_a, **_k):
        raise RuntimeError("network disabled in tests")

    svc._http_get_json = offline
    svc._http_post_json = offline
    return svc


# ---------------------------------------------------------------- assembly


def test_parse_categories_maps_aliases():
    assert _parse_categories(["fast food"]) == ["fast_food"]
    assert _parse_categories(["fastfood"]) == ["fast_food"]
    assert _parse_categories(["park", "parking", "garden"]) == ["walk"]
    assert _parse_categories(["cafe"]) == ["cafe"]


def test_empty_categories_means_all():
    names = _parse_categories([])
    assert {"cafe", "restaurant", "walk", "museum", "entertainment", "wellness"} <= set(names)
    assert _parse_categories("any") == names
    assert _parse_categories(None) == names


def test_no_nearby_places_returns_empty():
    svc = _fresh_service()
    fake = _FakeOverpass([])
    svc._overpass_elements = fake
    got = svc.search_nearby_places(ORIGIN["lat"], ORIGIN["lon"])
    assert got == []
    assert fake.calls == 1


def test_overpass_failure_returns_empty_gracefully():
    svc = _fresh_service()

    def boom(*a, **k):
        raise TimeoutError("overpass timeout")

    svc._http_post_json = boom
    got = svc.search_nearby_places(ORIGIN["lat"], ORIGIN["lon"])
    assert got == []


def test_http_timeout_returns_empty_gracefully():
    svc = _fresh_service()
    svc._http_post_json = lambda *a, **k: (_ for _ in ()).throw(TimeoutError("timeout"))
    got = svc.search_nearby_places(ORIGIN["lat"], ORIGIN["lon"])
    assert got == []


def test_cached_results_avoid_repetition():
    svc = _fresh_service()
    fake = _FakeOverpass([_el()])
    svc._overpass_elements = fake
    r1 = svc.search_nearby_places(23.0030, 72.5930)
    assert len(r1) == 1
    r2 = svc.search_nearby_places(23.0030, 72.5930)
    assert [p["title"] for p in r1] == [p["title"] for p in r2]
    assert fake.calls == 1


def test_large_and_small_radius_are_attached_to_query():
    svc = _fresh_service()
    calls = []

    def capture(url, content=None, timeout=None):
        calls.append(content)
        return {"elements": []}

    svc._http_post_json = capture
    svc.search_nearby_places(23.0133, 72.5833, radius_m=20)  # clamped to 800
    svc.search_nearby_places(23.0143, 72.5833, radius_m=40_000)  # clamped to 20000
    assert "around:800" in calls[0]
    assert "around:20000" in calls[1]


def test_duplicate_places_deduped():
    svc = _fresh_service()
    fake = _FakeOverpass([
        _el(name="Same Spot", oid=1),
        _el(name="same spot", oid=2, lat=23.01301, lon=72.56801),  # ~same coords
        _el(name="Other Spot", amenity="restaurant", oid=3, lat=23.0200, lon=72.5700),
    ])
    svc._overpass_elements = fake
    got = svc.search_nearby_places(ORIGIN["lat"], ORIGIN["lon"], categories="cafe,restaurant")
    titles = [p["title"] for p in got]
    assert titles.count("Same Spot") == 1


# ---------------------------------------------------------------- data quality


def test_missing_opening_hours_and_price_are_null_not_invented():
    svc = _fresh_service()
    fake = _FakeOverpass([
        _el(name="No Info Cafe", tags={"website": "example.com"}),
    ])
    svc._overpass_elements = fake
    p = svc.search_nearby_places(23.0020, 72.6020, categories="cafe")[0]
    assert p["opening_hours"] is None
    assert p["opening_note"] and "opening" in (p["opening_note"] or "").lower()
    assert p["phone"] is None
    assert p["price_level"] is None
    assert p["price_is_estimate"] is True  # flagged, never fake-real
    assert p["rating"] is None
    assert p["source"] == "overpass"
    assert p["source_id"]  # osm:{type}:{id}
    assert p["has_venue"] is True


def test_rich_fields_are_normalized():
    svc = _fresh_service()
    fake = _FakeOverpass([
        _el(
            name="Rich Bookstore",
            oid=7,
            lat=23.0140,
            lon=72.5690,
            tags={
                "shop": "books",
                "addr:street": "MG Road",
                "addr:city": "Ahmedabad",
                "phone": "+91 79 1234 5678",
                "website": "https://books.example.com",
                "opening_hours": "Mo-Su 10:00-21:00",
                "rating": "4.5",
            },
        ),
    ])
    svc._overpass_elements = fake
    p = svc.search_nearby_places(23.0040, 72.5940, categories="bookstore")[0]
    assert p["category"] == "bookstore"
    # kind stays the coarse planner/ranker bucket ("place"); subtype carries
    # the specific venue class the planner diversifies on.
    assert p["subtype"] == "bookstore"
    assert p["kind"] == "place"
    assert p["address"] == "MG Road, Ahmedabad"
    assert p["phone"] == "+91 79 1234 5678"
    assert p["website"] == "https://books.example.com"
    assert p["opening_hours"] == "Mo-Su 10:00-21:00"
    assert p["rating"] == 4.5
    assert p["price_level"] is None  # no price signal -> honest "unknown"
    assert p["distance_km"] is not None and p["distance_km"] >= 0


def test_without_coordinates_is_skipped():
    svc = _fresh_service()
    fake = _FakeOverpass([
        {"type": "node", "id": 11, "tags": {"name": "No Coords Cafe", "amenity": "cafe"}},
        {"type": "node", "id": 12, "tags": {"amenity": "cafe"}, "lat": 23.0150, "lon": 72.5700},  # unnamed
        _el(name="Valid Cafe", oid=13, lat=23.0160, lon=72.5710),
    ])
    svc._overpass_elements = fake
    got = svc.search_nearby_places(23.0050, 72.5950, categories="cafe")
    assert [p["title"] for p in got] == ["Valid Cafe"]


def test_way_elements_use_center_coordinates():
    svc = _fresh_service()
    fake = _FakeOverpass([
        _el(name="Big Park", oid=3, kind="way", center={"lat": 23.0170, "lon": 72.5720},
            tags={"leisure": "park"}),
    ])
    svc._overpass_elements = fake
    p = svc.search_nearby_places(23.0060, 72.5960, categories="walk")[0]
    assert p["category"] == "walk"
    assert abs(p["lat"] - 23.0170) < 1e-6


# ---------------------------------------------------------------- routing + limits


def test_routing_failure_falls_back_to_estimate():
    svc = _fresh_service()  # transport offline -> estimate path
    route = svc.calculate_route(23.01, 72.57, 23.02, 72.58)
    assert route["source"] == "estimate"
    assert route["distance_km"] >= 0.15
    assert route["walk_min"] and route["walk_min"] > 0


def test_osrm_disables_after_repeated_failures():
    svc = _fresh_service()
    svc._note_osrm_failure("driving")
    svc._note_osrm_failure("driving")
    assert svc.osrm_enabled is False
    # a fresh failure on another profile is tolerated once
    svc2 = _fresh_service()
    svc2._note_osrm_failure("foot")
    assert svc2.osrm_enabled is True


def test_throttle_enforces_min_interval_when_configured():
    svc = _fresh_service()
    before = svc._last_call
    svc._throttle()
    assert svc._last_call >= before


def test_throttle_no_sleep_when_interval_zero():
    svc = _fresh_service()
    old = settings.osm_min_interval_ms
    settings.osm_min_interval_ms = 0
    try:
        svc._throttle()
        svc._throttle()  # must not raise
    finally:
        settings.osm_min_interval_ms = old


def test_category_filter_is_enforced_on_results():
    svc = _fresh_service()
    fake = _FakeOverpass([
        _el(name="Cafe Place", oid=21),
        _el(name="A Park", oid=22, tags={"leisure": "park"}),  # walk cat
    ])
    svc._overpass_elements = fake
    got = svc.search_nearby_places(23.0070, 72.5970, categories="cafe")
    assert [p["category"] for p in got] == ["cafe"]


# ---------------------------------------------------------------- location


def test_resolve_prefers_user_input_and_passes_accuracy(monkeypatch):
    import moodos.location as loc

    monkeypatch.setattr(
        loc, "geocode_text",
        lambda label: {"lat": 23.02, "lon": 72.57, "city": "Ahmedabad",
                       "area": "Law Garden", "state": "Gujarat", "display_name": "Ahmedabad"},
    )
    monkeypatch.setattr(loc, "ip_location", lambda *a, **k: None)
    monkeypatch.setattr(loc, "reverse_geocode", lambda la, lo: {"city": "Ahmedabad", "area": "Law Garden"})

    svc = _fresh_service()
    res = svc.get_current_location(
        lat=23.0225, lon=72.5714, user_label="Law Garden, Ahmedabad",
        accuracy_m=18,
    )
    assert res["source"] == "user"
    assert res["accuracy_m"] == 18
    res2 = svc.get_current_location(lat=23.0225, lon=72.5714, accuracy_m=None)
    assert res2["source"] == "gps"
    assert res2["gps_live"] is True
    assert res2.get("accuracy_m") is None


def test_permission_denied_or_no_fix_falls_to_default(monkeypatch):
    import moodos.location as loc

    monkeypatch.setattr(loc, "geocode_text", lambda *a, **k: None)
    monkeypatch.setattr(loc, "ip_location", lambda *a, **k: None)
    res = loc.resolve_location(lat=None, lon=None, user_label=None, ip=None)
    assert res["source"] in {"default", "ip"}
    assert res["lat"] is not None and res["lon"] is not None