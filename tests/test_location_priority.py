"""Phase 2 — location accuracy: hybrid input (GPS + typed city).

Contract under test (see BUGLOG.md PHASE 2):
  a) typed place in the CURRENT request wins
  b) else GPS sent with the request
  c) else saved profile location, ANNOUNCED
  d) else a clear "location required" error — never a silent city

Plus: coordinate validation (range + swap), one shared helper for all five
location tools, and a place-result shape of name/address/lat/lon/distance_km/
source with radius filtering and nearest-first sorting.
"""

from __future__ import annotations

import pytest

from moodos.geo import (
    LocationError,
    ProviderUnavailable,
    haversine_km,
    normalize_places,
    validate_coords,
)

# Two far-apart cities: Ahmedabad (Gujarat) and Delhi.
AHMEDABAD = (23.0225, 72.5714)
DELHI = (28.6139, 77.2090)


# --------------------------------------------------------------- geometry


def test_validate_coords_accepts_in_range():
    assert validate_coords(23.0225, 72.5714) == (23.0225, 72.5714)
    assert validate_coords(-90, 180) == (-90.0, 180.0)
    assert validate_coords("23.0", "72.5") == (23.0, 72.5)


def test_validate_coords_rejects_out_of_range():
    # 200 is not a legal latitude AND not a legal longitude, so there is no
    # swap to suggest — it is simply out of range.
    with pytest.raises(LocationError) as exc:
        validate_coords(200.0, 72.5)
    assert exc.value.code == "coords_out_of_range"


def test_validate_coords_flags_a_latitude_that_only_fits_a_longitude():
    # 91 is impossible as a latitude but legal as a longitude, so the pair is
    # recoverable by swapping rather than being junk.
    with pytest.raises(LocationError) as exc:
        validate_coords(91.0, 72.5)
    assert exc.value.code == "coords_swapped"


def test_validate_coords_detects_swapped_pair():
    # 100 is not a legal latitude but is a legal longitude, while 20 is a
    # legal latitude — so the pair is recoverable by swapping and we must
    # say so rather than clamp or silently accept.
    with pytest.raises(LocationError) as exc:
        validate_coords(100.0, 20.0)
    assert exc.value.code == "coords_swapped"
    assert exc.value.details["suggestion"] == {"lat": 20.0, "lon": 100.0}


def test_validate_coords_rejects_a_pair_that_is_wrong_both_ways():
    with pytest.raises(LocationError) as exc:
        validate_coords(200.0, 400.0)
    assert exc.value.code == "coords_out_of_range"


def test_validate_coords_rejects_non_numeric():
    with pytest.raises(LocationError) as exc:
        validate_coords("north", "east")
    assert exc.value.code == "invalid_coords"


def test_haversine_between_two_far_cities():
    km = haversine_km(*AHMEDABAD, *DELHI)
    assert 700 < km < 900  # ~776 km


# ------------------------------------------------------------ normalize


def _row(name, lat, lon, **kw):
    return {"name": name, "lat": lat, "lon": lon, "source": "overpass", **kw}


def test_normalize_places_guarantees_the_contract_fields():
    rows = normalize_places(
        [_row("Cafe A", 23.03, 72.58, address="MG Road")], *AHMEDABAD, radius_km=5
    )
    assert rows[0]["name"] == "Cafe A"
    assert rows[0]["address"] == "MG Road"
    assert isinstance(rows[0]["lat"], float)
    assert isinstance(rows[0]["lon"], float)
    assert isinstance(rows[0]["distance_km"], float)
    assert rows[0]["source"] == "overpass"


def test_normalize_places_drops_rows_with_missing_coordinates():
    rows = normalize_places(
        [
            _row("Good", 23.03, 72.58),
            {"name": "No coords", "source": "overpass"},
            {"name": "None coords", "lat": None, "lon": None, "source": "overpass"},
            {"name": "Bad coords", "lat": "x", "lon": "y", "source": "overpass"},
        ],
        *AHMEDABAD,
        radius_km=50,
    )
    assert [r["name"] for r in rows] == ["Good"]


def test_normalize_places_filters_by_radius_and_sorts_nearest_first():
    near = _row("Near", 23.03, 72.58)
    far = _row("Far", 23.20, 72.58)  # ~19 km north
    rows = normalize_places([far, near], *AHMEDABAD, radius_km=5)
    assert [r["name"] for r in rows] == ["Near"]
    assert rows[0]["distance_km"] <= 5.0


def test_normalize_places_computes_distance_when_provider_omits_it():
    rows = normalize_places([_row("Cafe", 23.03, 72.58)], *AHMEDABAD, radius_km=50)
    assert rows[0]["distance_km"] == pytest.approx(
        haversine_km(*AHMEDABAD, 23.03, 72.58), abs=0.01
    )


def test_normalize_places_uses_title_when_name_is_absent():
    rows = normalize_places(
        [{"title": "Titled Only", "lat": 23.03, "lon": 72.58, "source": "x"}],
        *AHMEDABAD, radius_km=50,
    )
    assert rows[0]["name"] == "Titled Only"
    assert rows[0]["title"] == "Titled Only"


# ------------------------------------------------------- priority order


def _stub(monkeypatch, **kw):
    import moodos.location as loc

    monkeypatch.setattr(loc, "geocode_text", kw.get("geocode", lambda *a, **k: None))
    monkeypatch.setattr(loc, "ip_location", kw.get("ip", lambda *a, **k: None))
    monkeypatch.setattr(loc, "reverse_geocode", kw.get("reverse", lambda a, b: {}))
    if "profile" in kw:
        monkeypatch.setattr(loc, "_profile_location", lambda: kw["profile"])
    return loc


def test_typed_place_outranks_gps(monkeypatch):
    loc = _stub(
        monkeypatch,
        geocode=lambda t: {"lat": 21.5, "lon": 70.46, "city": "Junagadh",
                           "state": "Gujarat", "country_code": "in",
                           "candidates": [], "ambiguous": False},
    )
    res = loc.resolve_location(*AHMEDABAD, user_label="Junagadh")
    assert res["source"] == "user"
    assert (res["lat"], res["lon"]) == (21.5, 70.46)


def test_typed_city_text_is_geocoded_not_used_as_a_label(monkeypatch):
    """A typed city must become real coordinates via a provider, not a string."""
    seen = {}

    def fake_geocode(text):
        seen["text"] = text
        return {"lat": 19.0760, "lon": 72.8777, "city": "Mumbai",
                "state": "Maharashtra", "country_code": "in",
                "candidates": [], "ambiguous": False}

    loc = _stub(monkeypatch, geocode=fake_geocode)
    res = loc.resolve_location(*AHMEDABAD, user_label="Mumbai")
    assert seen["text"] == "Mumbai"
    assert res["source"] == "user"
    assert (res["lat"], res["lon"]) == (19.0760, 72.8777)


def test_gps_outranks_ip(monkeypatch):
    loc = _stub(
        monkeypatch,
        ip=lambda *a, **k: {"lat": 28.6, "lon": 77.2, "city": "Delhi"},
    )
    res = loc.resolve_location(*AHMEDABAD, user_label=None)
    assert res["source"] == "gps"
    assert (res["lat"], res["lon"]) == AHMEDABAD


def test_ip_outranks_profile_and_is_labelled(monkeypatch):
    loc = _stub(
        monkeypatch,
        ip=lambda *a, **k: {"lat": 28.6, "lon": 77.2, "city": "Delhi"},
        profile={"lat": 12.97, "lon": 77.59, "source": "profile",
                 "confidence": 0.10, "label": "saved profile location (Bengaluru)",
                 "notice": "using saved profile location"},
    )
    res = loc.resolve_location(lat=None, lon=None, user_label=None)
    assert res["source"] == "ip"
    assert (res["lat"], res["lon"]) == (28.6, 77.2)


def test_profile_is_last_resort_and_announced(monkeypatch):
    loc = _stub(
        monkeypatch,
        profile={"lat": 12.97, "lon": 77.59, "source": "profile",
                 "confidence": 0.10, "label": "saved profile location (Bengaluru)",
                 "notice": "No live location for this request - using your saved "
                           "profile location: Bengaluru."},
    )
    res = loc.resolve_location(lat=None, lon=None, user_label=None)
    assert res["source"] == "profile"
    assert res["notice"].startswith("No live location")


def test_ambiguous_typed_name_returns_full_addresses_to_confirm(monkeypatch):
    loc = _stub(
        monkeypatch,
        geocode=lambda t: {
            "lat": 37.0, "lon": -93.0, "city": "Springfield", "state": "Missouri",
            "country_code": "us", "display_name": "Springfield, Missouri, United States",
            "candidates": [
                {"lat": 37.0, "lon": -93.0, "display_name": "Springfield, Missouri, United States",
                 "state": "Missouri", "country_code": "us"},
                {"lat": 39.8, "lon": -89.6, "display_name": "Springfield, Illinois, United States",
                 "state": "Illinois", "country_code": "us"},
            ],
            "ambiguous": True,
        },
    )
    res = loc.resolve_location(*AHMEDABAD, user_label="Springfield")
    assert res["needs_confirmation"] is True
    names = [c["display_name"] for c in res["candidates"]]
    assert "Springfield, Missouri, United States" in names
    assert "Springfield, Illinois, United States" in names
    assert "confirm" in res["notice"].lower()


def test_ungeocodable_typed_name_is_an_error_not_a_silent_fallback(monkeypatch):
    loc = _stub(monkeypatch, geocode=lambda t: None)
    with pytest.raises(LocationError) as exc:
        loc.resolve_location(*AHMEDABAD, user_label="zzzz nowhere")
    assert exc.value.code == "geocode_failed"


def test_half_a_gps_fix_is_rejected(monkeypatch):
    loc = _stub(monkeypatch)
    with pytest.raises(LocationError) as exc:
        loc.resolve_location(lat=23.0, lon=None)
    assert exc.value.code == "invalid_coords"


def test_swapped_gps_fix_is_rejected_with_a_suggestion(monkeypatch):
    loc = _stub(monkeypatch)
    with pytest.raises(LocationError) as exc:
        loc.resolve_location(lat=100.0, lon=20.0)
    assert exc.value.code == "coords_swapped"


# ----------------------------------------------- two far-apart cities


class _FakeOverpassFor:
    """Returns canned POIs positioned around whichever city was asked for."""

    def __init__(self):
        self.seen = []

    def __call__(self, lat, lon, radius_m, cats):
        self.seen.append((lat, lon, radius_m))
        base_lat, base_lon = lat, lon
        return [
            {"type": "node", "id": 1, "lat": base_lat + 0.005, "lon": base_lon,
             "tags": {"name": "City Cafe", "amenity": "cafe"}},
            {"type": "node", "id": 2, "lat": base_lat + 0.20, "lon": base_lon,
             "tags": {"name": "Too Far Cafe", "amenity": "cafe"}},
        ]


def test_two_far_apart_cities_return_different_and_in_radius_results(monkeypatch):
    from moodos.location_service import location_service as svc
    from moodos.mcp_server import mcp

    fake = _FakeOverpassFor()
    monkeypatch.setattr(svc, "_overpass_elements", fake)
    monkeypatch.setattr(svc, "_attach_route_times", lambda places, lat, lon: None)

    a = mcp.call("find_nearby_places", lat=AHMEDABAD[0], lon=AHMEDABAD[1], q="cafe")
    d = mcp.call("find_nearby_places", lat=DELHI[0], lon=DELHI[1], q="cafe")

    # Results change with the resolved coordinates.
    assert fake.seen[0][:2] == AHMEDABAD
    assert fake.seen[1][:2] == DELHI
    assert a and d
    assert a[0]["lat"] != d[0]["lat"]

    # Every result stays inside the requested radius, nearest-first.
    for rows, origin in ((a, AHMEDABAD), (d, DELHI)):
        assert [r["name"] for r in rows] == ["City Cafe"]  # "Too Far" filtered out
        assert rows[0]["distance_km"] <= 4.0
        assert rows[0]["distance_km"] == pytest.approx(
            haversine_km(*origin, rows[0]["lat"], rows[0]["lon"]), abs=0.01
        )


def test_gps_and_typed_input_produce_different_tool_results(monkeypatch):
    import moodos.location as loc
    from moodos.location_service import location_service as svc
    from moodos.mcp_server import mcp

    svc._overpass_elements = _FakeOverpassFor()
    monkeypatch.setattr(svc, "_attach_route_times", lambda places, lat, lon: None)
    _stub(
        monkeypatch,
        geocode=lambda t: {"lat": DELHI[0], "lon": DELHI[1], "city": "Delhi",
                           "state": "Delhi", "country_code": "in",
                           "candidates": [], "ambiguous": False},
    )

    gps = loc.resolve_location(*AHMEDABAD, user_label=None)
    typed = loc.resolve_location(*AHMEDABAD, user_label="Delhi")
    assert (gps["lat"], gps["lon"]) == AHMEDABAD
    assert (typed["lat"], typed["lon"]) == DELHI

    from_gps = mcp.call("find_nearby_places", lat=gps["lat"], lon=gps["lon"], q="cafe")
    from_typed = mcp.call("find_nearby_places", lat=typed["lat"], lon=typed["lon"], q="cafe")
    assert from_gps[0]["lat"] != from_typed[0]["lat"]


# ----------------------------------------- the five location tools


FIVE_TOOLS = [
    ("find_nearby_places", {"lat": 23.02, "lon": 72.57, "q": "cafe"}),
    ("find_nearby_cinemas", {"lat": 23.02, "lon": 72.57}),
    ("search_restaurants", {"lat": 23.02, "lon": 72.57}),
    ("search_restaurants_by_mood", {"lat": 23.02, "lon": 72.57, "mood": "calm"}),
    ("get_weather", {"lat": 23.02, "lon": 72.57}),
]


@pytest.mark.parametrize("tool,kwargs", FIVE_TOOLS, ids=[t for t, _ in FIVE_TOOLS])
def test_every_location_tool_shares_one_coordinate_validator(tool, kwargs):
    from moodos.mcp_server import mcp

    with pytest.raises(LocationError) as exc:
        mcp.call(tool, **{**kwargs, "lat": 200.0})
    assert exc.value.code == "coords_out_of_range"

    with pytest.raises(LocationError) as exc:
        mcp.call(tool, **{**kwargs, "lat": None, "lon": None})
    assert exc.value.code == "invalid_coords"


@pytest.mark.parametrize("tool,kwargs", FIVE_TOOLS, ids=[t for t, _ in FIVE_TOOLS])
def test_every_location_tool_reports_a_dead_provider(monkeypatch, tool, kwargs):
    """A failing provider is an honest error, never an empty fake-success."""
    from moodos import mcp_server as ms
    from moodos.mcp_server import mcp

    def boom(*a, **k):
        raise ProviderUnavailable("overpass", "Overpass is down for this test")

    if tool == "get_weather":
        monkeypatch.setattr(ms.providers, "get_weather", boom)
    elif tool == "find_nearby_places":
        monkeypatch.setattr(ms.location_service, "search_nearby_places", boom)
    elif tool == "find_nearby_cinemas":
        monkeypatch.setattr(ms.providers, "nearby_cinemas", boom)
    else:
        monkeypatch.setattr(ms.providers, "search_restaurants_by_mood", boom)
        monkeypatch.setattr(ms.providers, "nearby_restaurants", boom)

    with pytest.raises(ProviderUnavailable):
        mcp.call(tool, **kwargs)


def test_place_tools_return_the_full_row_contract(monkeypatch):
    from moodos import mcp_server as ms
    from moodos.mcp_server import mcp

    monkeypatch.setattr(
        ms.location_service, "search_nearby_places",
        lambda *a, **k: [
            {"name": "Row A", "lat": 23.03, "lon": 72.58, "source": "overpass"},
            {"name": "Row B", "lat": 23.04, "lon": 72.59, "source": "overpass",
             "address": "Ellisbridge"},
            {"name": "No position", "source": "overpass"},
        ],
    )
    rows = mcp.call("find_nearby_places", lat=23.02, lon=72.57, q="cafe")
    assert [r["name"] for r in rows] == ["Row A", "Row B"]
    for r in rows:
        assert set(("name", "address", "lat", "lon", "distance_km", "source")) <= set(r)
    assert rows[1]["address"] == "Ellisbridge"


def test_get_weather_rejects_impossible_coordinates():
    from moodos.mcp_server import mcp

    with pytest.raises(LocationError):
        mcp.call("get_weather", lat=999.0, lon=0.0)


# ------------------------------------------------------- HTTP surface


def _client():
    from fastapi.testclient import TestClient

    import app as appmod

    return TestClient(appmod.app), appmod


def test_plan_endpoint_with_swapped_coords_is_a_clear_400():
    client, _ = _client()
    res = client.post("/api/plan", json={
        "message": "plan me an evening", "user_id": "swap_test",
        "lat": 100.0, "lon": 20.0,
    })
    assert res.status_code == 400
    body = res.json()
    assert body["error"] == "coords_swapped"
    assert body["explanation"]


def test_plan_endpoint_with_impossible_coords_is_a_clear_400():
    client, _ = _client()
    res = client.post("/api/plan", json={
        "message": "plan me an evening", "user_id": "range_test",
        "lat": 200.0, "lon": 400.0,
    })
    assert res.status_code == 400
    assert res.json()["error"] == "coords_out_of_range"


def test_plan_endpoint_with_typed_city_uses_the_geocoded_coords(monkeypatch):
    """`city` used to be a display label only — it must now set the coords."""
    client, appmod = _client()
    import moodos.location as loc

    monkeypatch.setattr(
        loc, "geocode_text",
        lambda t: {"lat": DELHI[0], "lon": DELHI[1], "city": "Delhi",
                   "state": "Delhi", "country_code": "in",
                   "candidates": [], "ambiguous": False},
    )
    monkeypatch.setattr(loc, "ip_location", lambda *a, **k: None)
    monkeypatch.setattr(loc, "reverse_geocode", lambda a, b: {"city": "Delhi"})
    # The app imported the name directly, so patch it where the route reads it.
    monkeypatch.setattr(appmod, "resolve_location", loc.resolve_location)

    captured = {}

    def fake_handle(message, user_id, lat, lon, prompt, location_names=None):
        captured.update(lat=lat, lon=lon, names=location_names)
        return {"mode": "plan", "ok": True}

    monkeypatch.setattr(appmod, "handle_message", fake_handle)

    res = client.post("/api/plan", json={
        "message": "plan me an evening", "user_id": "city_test",
        "lat": AHMEDABAD[0], "lon": AHMEDABAD[1], "city": "Delhi",
    })
    assert res.status_code == 200
    assert captured["lat"] == DELHI[0]
    assert captured["lon"] == DELHI[1]
    assert captured["names"]["city"] == "Delhi"
    assert captured["names"]["source"] == "user"


def test_plan_endpoint_reports_a_dead_provider_as_503(monkeypatch):
    """A missing/failing provider is an honest error, not a 200 with no data."""
    from moodos.geo import ProviderUnavailable

    client, appmod = _client()
    import moodos.location as loc

    monkeypatch.setattr(
        loc, "geocode_text",
        lambda t: {"lat": AHMEDABAD[0], "lon": AHMEDABAD[1], "city": "Ahmedabad",
                   "state": "Gujarat", "country_code": "in",
                   "candidates": [], "ambiguous": False},
    )
    monkeypatch.setattr(loc, "ip_location", lambda *a, **k: None)
    monkeypatch.setattr(loc, "reverse_geocode", lambda a, b: {"city": "Ahmedabad"})
    monkeypatch.setattr(appmod, "resolve_location", loc.resolve_location)

    def dead(message, user_id, lat, lon, prompt, location_names=None):
        raise ProviderUnavailable("overpass", "Overpass is down")

    monkeypatch.setattr(appmod, "handle_message", dead)

    res = client.post("/api/plan", json={
        "message": "plan me an evening", "user_id": "down_test",
        "lat": AHMEDABAD[0], "lon": AHMEDABAD[1],
    })
    assert res.status_code == 503
    assert res.json()["provider"] == "overpass"


def test_restaurants_endpoint_never_silently_uses_the_default_city(monkeypatch):
    """Every source stripped -> a clear "location required", not Ahmedabad."""
    client, appmod = _client()
    import moodos.location as loc

    monkeypatch.setattr(loc, "geocode_text", lambda *a, **k: None)
    monkeypatch.setattr(loc, "ip_location", lambda *a, **k: None)
    monkeypatch.setattr(loc, "_profile_location", lambda: None)
    monkeypatch.setattr(appmod, "resolve_location", loc.resolve_location)

    res = client.get("/api/restaurants")
    assert res.status_code == 428
    assert res.json()["error"] == "location_required"


def test_restaurants_endpoint_uses_a_typed_city(monkeypatch):
    client, appmod = _client()
    import moodos.location as loc

    monkeypatch.setattr(
        loc, "geocode_text",
        lambda t: {"lat": DELHI[0], "lon": DELHI[1], "city": "Delhi",
                   "state": "Delhi", "country_code": "in",
                   "candidates": [], "ambiguous": False},
    )
    monkeypatch.setattr(loc, "ip_location", lambda *a, **k: None)
    monkeypatch.setattr(loc, "reverse_geocode", lambda a, b: {"city": "Delhi"})
    monkeypatch.setattr(appmod, "resolve_location", loc.resolve_location)
    monkeypatch.setattr(
        appmod.mcp, "call",
        lambda name, **kw: [{"name": "Stub", "lat": kw["lat"], "lon": kw["lon"],
                             "source": "overpass"}],
    )

    res = client.get("/api/restaurants", params={"city": "Delhi"})
    assert res.status_code == 200
    body = res.json()
    assert (body["lat"], body["lon"]) == DELHI
    assert body["location"]["source"] == "user"


def test_ambiguous_city_is_surfaced_as_409_with_candidates(monkeypatch):
    client, appmod = _client()
    import moodos.location as loc

    monkeypatch.setattr(
        loc, "geocode_text",
        lambda t: {"lat": 37.0, "lon": -93.0, "city": "Springfield",
                   "state": "Missouri", "country_code": "us",
                   "display_name": "Springfield, Missouri, United States",
                   "candidates": [
                       {"display_name": "Springfield, Missouri, United States"},
                       {"display_name": "Springfield, Illinois, United States"},
                   ],
                   "ambiguous": True},
    )
    monkeypatch.setattr(loc, "ip_location", lambda *a, **k: None)
    monkeypatch.setattr(loc, "reverse_geocode", lambda a, b: {"city": "Springfield"})
    monkeypatch.setattr(appmod, "resolve_location", loc.resolve_location)

    res = client.post("/api/plan", json={
        "message": "plan me an evening", "user_id": "amb_test",
        "user_label": "Springfield",
    })
    assert res.status_code == 409
    body = res.json()
    assert body["error"] == "location_ambiguous"
    assert len(body["candidates"]) == 2


def test_profile_fallback_is_announced_through_the_api(monkeypatch):
    """(c) saved profile location — allowed, but the user must be told."""
    client, appmod = _client()
    import moodos.location as loc

    monkeypatch.setattr(loc, "geocode_text", lambda *a, **k: None)
    monkeypatch.setattr(loc, "ip_location", lambda *a, **k: None)
    monkeypatch.setattr(
        loc, "_profile_location",
        lambda: {"lat": 12.97, "lon": 77.59, "source": "profile", "confidence": 0.10,
                 "label": "saved profile location (Bengaluru)",
                 "notice": "No live location - using saved profile location: Bengaluru."},
    )
    monkeypatch.setattr(loc, "reverse_geocode", lambda a, b: {"city": "Bengaluru"})
    monkeypatch.setattr(appmod, "resolve_location", loc.resolve_location)

    captured = {}

    def fake_handle(message, user_id, lat, lon, prompt, location_names=None):
        captured.update(lat=lat, lon=lon, names=location_names)
        return {"mode": "plan", "ok": True, "location": {}}

    monkeypatch.setattr(appmod, "handle_message", fake_handle)

    res = client.post("/api/plan", json={
        "message": "plan me an evening", "user_id": "profile_test",
    })
    assert res.status_code == 200
    assert captured["lat"] == 12.97
    assert captured["lon"] == 77.59
    assert captured["names"]["source"] == "profile"
    assert captured["names"]["notice"]
    assert res.json()["location"]["resolver"]["notice"]
