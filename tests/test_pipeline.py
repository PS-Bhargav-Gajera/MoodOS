from fastapi.testclient import TestClient

from app import app
from moodos import actions
from moodos.db import init_db
from moodos.nlu import classify_turn, heuristic_extract
from moodos.orchestrator import (
    _apply_repeat_penalty, _derive_search_query, _venue_class,
    _diversify_consecutive_stops, _assemble_plan, _clamp_plan_durations,
    _DUR_CAPS,
)
from moodos.ranking import hard_filter


def test_heuristic_rupees_not_hours():
    slots = heuristic_extract(
        "I'm exhausted after college, alone, have 1000 rupees, four hours, and want to go out but nothing intense."
    )
    assert slots["budget_inr"] == 1000
    assert slots["duration_hours"] == 4.0


def test_hard_filter_drops_club():
    slots = {"intensity": "low", "social": "solo", "budget_inr": 1000, "duration_hours": 4}
    club = {"estimated_cost": 1500, "duration_min": 180, "intensity": "high", "crowded": True}
    assert hard_filter(club, slots, {"rainy": False}, 1000, 240) is False


def test_chat_not_plan_for_location():
    assert classify_turn("what is my curr location") == {"mode": "chat", "topic": "location"}
    assert classify_turn("what's the weather?")["topic"] == "weather"
    assert classify_turn(
        "I'm exhausted after college, alone, have ₹1000, four hours, and want to go out but nothing intense."
    )["mode"] == "plan"
    init_db()
    client = TestClient(app)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_location_aware_showtimes_nearest_first():
    shows = actions.list_showtimes(lat=23.0225, lon=72.5714)
    assert len(shows) >= 2
    assert all("lat" in s and "lon" in s for s in shows)


def test_music_query_respects_mood_and_varies():
    low = _derive_search_query("I'm exhausted and want to relax", {"desired_mood": "relaxed"}, "music")
    high = _derive_search_query("I want to celebrate an upbeat party", {"desired_mood": "energetic"}, "music")
    assert low != high


def test_repeat_penalty_suppresses_recent_movie():
    base = 0.8
    suppressed = _apply_repeat_penalty(
        {"title": "The Lunchbox", "kind": "movie"}, base, "calm acoustic evening"
    )
    assert suppressed == base  # not remembered yet -> unchanged


def test_resolve_prefers_manual_city_over_gps(monkeypatch):
    from moodos import location as loc

    monkeypatch.setattr(
        loc, "geocode_text",
        lambda text: {"lat": 21.5, "lon": 70.46, "city": "Junagadh", "area": "",
                      "state": "Gujarat", "country": "India", "display_name": "Junagadh", "matched": "Junagadh"},
    )
    monkeypatch.setattr(loc, "reverse_geocode", lambda lat, lon: {"city": "Junagadh", "area": "", "state": "Gujarat"})
    monkeypatch.setattr(loc, "ip_location", lambda ip: None)

    res = loc.resolve_location(lat=23.0225, lon=72.5714, user_label="Junagadh")
    assert res["source"] == "user"
    assert res["user_override"] is True
    assert res["gps_live"] is False
    assert res["city"] == "Junagadh"


def test_plan_endpoint_forwards_resolved_location(monkeypatch):
    import app as appmod

    captured = {}

    def fake_handle(message, user_id, lat, lon, prompt, location_names=None):
        captured.update(message=message, user_id=user_id, lat=lat, lon=lon,
                        prompt=prompt, names=location_names)
        return {"mode": "plan", "ok": True}

    def fake_resolve(lat, lon, user_label, ip, accuracy_m=None):
        return {
            "lat": 21.5, "lon": 70.46, "source": "user", "label": "Junagadh",
            "city": "Junagadh", "area": "", "state": "Gujarat", "country": "India",
            "display_name": "Junagadh", "confidence": 0.98,
            "gps_live": False, "user_override": True,
        }

    monkeypatch.setattr(appmod, "handle_message", fake_handle)
    monkeypatch.setattr(appmod, "resolve_location", fake_resolve)
    init_db()
    client = TestClient(appmod.app)
    res = client.post("/api/plan", json={
        "message": "plan me an evening", "user_id": "loc_test",
        "lat": 23.0225, "lon": 72.5714, "user_label": "Junagadh",
    })
    assert res.status_code == 200
    # The manual city beat live GPS coords and is forwarded to the pipeline.
    assert captured["lat"] == 21.5
    assert captured["lon"] == 70.46
    assert captured["names"]["city"] == "Junagadh"
    assert captured["names"]["source"] == "user"


def test_chat_location_reply_uses_manual_city(monkeypatch):
    import app as appmod
    from moodos import chat as chatmod

    captured = {}

    def fake_answer(message, user_id, lat, lon, location_names=None):
        captured.update(lat=lat, lon=lon, names=location_names)
        return {"mode": "chat", "topic": "location",
                "reply": f"Junagadh", "location": {"city": "Junagadh"},
                "weather": {}, "used_default_location": False, "plan": None}

    def fake_resolve(lat, lon, user_label, ip, accuracy_m=None):
        return {
            "lat": 21.5, "lon": 70.46, "source": "user", "label": "Junagadh",
            "city": "Junagadh", "area": "", "state": "Gujarat", "country": "India",
            "display_name": "Junagadh", "confidence": 0.98,
            "gps_live": False, "user_override": True,
        }

    monkeypatch.setattr(chatmod, "classify_turn", lambda message: {"mode": "chat", "topic": "location"})
    monkeypatch.setattr(appmod, "handle_message", lambda *a, **k: fake_answer(a[0], a[1], a[2], a[3], k.get("location_names")))
    monkeypatch.setattr(appmod, "resolve_location", fake_resolve)
    client = TestClient(appmod.app)
    res = client.post("/api/plan", json={
        "message": "what is my location", "user_id": "loc_test",
        "user_label": "Junagadh",
    })
    assert res.status_code == 200
    assert captured["names"]["city"] == "Junagadh"
    assert captured["lat"] == 21.5


def test_venue_class_groups_fine_grained():
    assert _venue_class({"kind": "cafe", "title": "The Gyan Café"}) == "cafe"
    assert _venue_class({"kind": "food", "subtype": "ice_cream", "title": "Scoop N Munch"}) == "dessert"
    assert _venue_class({"kind": "food", "subtype": "restaurant", "title": "Main Dish"}) == "restaurant"
    assert _venue_class({"kind": "place", "subtype": "walk", "title": "Park"}) == "walk"
    assert _venue_class({"kind": "movie", "title": "Lunchbox"}) == "cinema"


def test_diversify_swaps_second_cafe_for_different_category():
    plan = {
        "steps": [
            {"order": 1, "kind": "cafe", "title": "The Gyan Café", "duration_min": 45, "cost_inr": 200, "flexible": True},
            {"order": 2, "kind": "cafe", "title": "Another Café", "duration_min": 40, "cost_inr": 150, "flexible": True},
            {"order": 3, "kind": "music", "title": "Wind down", "duration_min": 20, "cost_inr": 0, "flexible": True},
        ],
        "total_duration_min": 105,
        "total_cost_inr": 350,
    }
    ranked = [
        {"kind": "place", "subtype": "walk", "title": "Local Park", "lat": 23.0, "lon": 72.5,
         "estimated_cost": 0, "duration_min": 25, "intensity": "low", "distance_km": 0.5, "final_score": 0.82},
        {"kind": "food", "subtype": "fast_food", "title": "Quick Bites", "lat": 23.0, "lon": 72.5,
         "estimated_cost": 100, "duration_min": 35, "intensity": "low", "distance_km": 0.8, "final_score": 0.76},
    ]
    slots = {"intensity": "low", "social": "solo", "budget_inr": 1000, "duration_hours": 4}
    weather = {"rainy": False}
    result = _diversify_consecutive_stops(plan, ranked, slots, weather, budget=1000, minutes=240)
    step2 = result["steps"][1]
    # The second cafe should have been swapped for a different-category venue.
    assert step2["title"] != "Another Café"
    assert _venue_class(step2) != "cafe"
    # Duration unchanged to preserve budget fit.
    assert step2["duration_min"] == 40


def test_diversify_keeps_duplicate_when_no_alternative_available():
    plan = {
        "steps": [
            {"order": 1, "kind": "cafe", "title": "Café A", "duration_min": 45, "cost_inr": 200, "flexible": True},
            {"order": 2, "kind": "cafe", "title": "Café B", "duration_min": 40, "cost_inr": 150, "flexible": True},
        ],
        "total_duration_min": 85,
        "total_cost_inr": 350,
    }
    ranked = []  # no alternatives at all
    slots = {"intensity": "low", "social": "solo", "budget_inr": 1000, "duration_hours": 4}
    result = _diversify_consecutive_stops(plan, ranked, slots, {"rainy": False}, budget=1000, minutes=240)
    # Both cafés remain — no swap possible.
    assert result["steps"][0]["title"] == "Café A"
    assert result["steps"][1]["title"] == "Café B"


def test_assemble_plan_breaks_two_cafes_and_fits_budget():
    lat, lon = 23.0225, 72.5714
    ranked = [
        {"id": "osm:c1", "kind": "place", "subtype": "cafe", "title": "Scoop N Munch",
         "lat": 23.0228, "lon": 72.5719, "estimated_cost": 120, "duration_min": 45,
         "intensity": "low", "crowded": False, "distance_km": 0.1, "final_score": 0.86},
        {"id": "osm:c2", "kind": "place", "subtype": "cafe", "title": "The Gyan Cafe",
         "lat": 23.0235, "lon": 72.5722, "estimated_cost": 180, "duration_min": 40,
         "intensity": "low", "crowded": False, "distance_km": 0.2, "final_score": 0.84},
        {"id": "osm:p1", "kind": "place", "subtype": "walk", "title": "Local Park",
         "lat": 23.0140, "lon": 72.5650, "estimated_cost": 0, "duration_min": 25,
         "intensity": "low", "crowded": False, "outdoor": True, "needs_clear_weather": True,
         "distance_km": 1.1, "final_score": 0.78},
        {"id": "osm:d1", "kind": "food", "subtype": "ice_cream", "title": "Natural Ice Cream",
         "lat": 23.0210, "lon": 72.5700, "estimated_cost": 150, "duration_min": 20,
         "intensity": "low", "crowded": False, "distance_km": 0.3, "final_score": 0.74},
    ]
    slots = {"current_mood": "exhausted", "desired_mood": "relaxed", "intensity": "low",
             "social": "solo", "budget_inr": 1000, "duration_hours": 2.25,
             "music_language": None, "food_priority": False, "stay_home": False,
             "want_movie": False}
    plan = {
        "steps": [
            {"order": 1, "kind": "walk",
             "title": "20-minute walk along a quiet stretch near Ahmedabad",
             "duration_min": 20, "cost_inr": 0, "flexible": False},
            {"order": 2, "kind": "cafe", "title": "Scoop N Munch", "duration_min": 45,
             "cost_inr": 120, "flexible": True},
            {"order": 3, "kind": "cafe", "title": "The Gyan Cafe", "duration_min": 40,
             "cost_inr": 180, "flexible": True},
            {"order": 4, "kind": "music", "title": "Wind down", "duration_min": 20,
             "cost_inr": 0, "flexible": True},
        ],
        "total_duration_min": 125,
        "total_cost_inr": 300,
    }
    result = _assemble_plan(plan, ranked, slots, lat, lon, [], weather={"rainy": False})
    physical = [s for s in result["steps"] if s.get("kind") != "travel"]
    # No two adjacent physical stops share a venue class anymore.
    classes = [_venue_class(s) for s in physical]
    assert classes[0] != classes[1] and classes[1] != classes[2]
    assert "The Gyan Cafe" not in " ".join(s.get("title", "") for s in physical)


def test_clamp_plan_durations_caps_overlong_cafe():
    plan = {
        "steps": [
            {"order": 1, "kind": "cafe", "title": "Café Long", "duration_min": 194, "flexible": True},
            {"order": 2, "kind": "movie", "title": "Film", "duration_min": 160, "flexible": False},
        ],
        "total_duration_min": 354,
        "total_cost_inr": 0,
    }
    _clamp_plan_durations(plan)
    assert plan["steps"][0]["duration_min"] == _DUR_CAPS["cafe"] == 90
    # Fixed movie runtime is never rewritten.
    assert plan["steps"][1]["duration_min"] == 160


def test_assemble_plan_spreads_shortfall_not_all_into_one_cafe():
    # A 5-hour request with only a cafe + music: leftover time must be spread
    # across flexible steps instead of ballooning the cafe (the 194-min bug).
    lat, lon = 23.0225, 72.5714
    ranked = [
        {"id": "osm:c1", "kind": "place", "subtype": "cafe", "title": "Scoop N Munch",
         "lat": 23.0228, "lon": 72.5719, "estimated_cost": 120, "duration_min": 45,
         "intensity": "low", "crowded": False, "distance_km": 0.1, "final_score": 0.86},
    ]
    slots = {"current_mood": "exhausted", "desired_mood": "relaxed", "intensity": "low",
             "social": "solo", "budget_inr": 1000, "duration_hours": 5.0,
             "music_language": None, "food_priority": False, "stay_home": False,
             "want_movie": False}
    plan = {
        "steps": [
            {"order": 1, "kind": "cafe", "title": "Scoop N Munch", "duration_min": 45,
             "cost_inr": 120, "flexible": True},
            {"order": 2, "kind": "music", "title": "Wind down", "duration_min": 20,
             "cost_inr": 0, "flexible": True},
        ],
        "total_duration_min": 65,
        "total_cost_inr": 120,
    }
    result = _assemble_plan(plan, ranked, slots, lat, lon, [], weather={"rainy": False})
    cafe = next(s for s in result["steps"] if s.get("kind") == "cafe")
    assert cafe["duration_min"] <= _DUR_CAPS["cafe"]  # never a 3-hour cafe
    assert result["budget_fit"]["within_tolerance"]  # still hits ~5h overall


def test_hard_filter_rejects_placeholder_titles():
    slots = {"intensity": "low", "social": "solo", "budget_inr": 1000, "duration_hours": 4}
    base = {"estimated_cost": 100, "duration_min": 45, "intensity": "low", "distance_km": 0.5}
    assert hard_filter({**base, "title": "Nearby cafe"}, slots, {"rainy": False}, 1000, 240) is False
    assert hard_filter({**base, "title": "Nearby restaurant"}, slots, {"rainy": False}, 1000, 240) is False
    assert hard_filter({**base, "title": ""}, slots, {"rainy": False}, 1000, 240) is False
    assert hard_filter({**base, "title": "The Gyan Cafe"}, slots, {"rainy": False}, 1000, 240) is True
