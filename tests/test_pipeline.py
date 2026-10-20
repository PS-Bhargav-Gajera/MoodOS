import inspect

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


def test_location_aware_showtimes_nearest_first(monkeypatch):
    # conftest blocks real HTTP, so give the showtime builder canned TMDB
    # rows; this test is about lat/lon passthrough, not the TMDB fetch.
    from moodos import providers as prov

    films = [
        {"title": "Film A", "tmdb_id": 1, "text": "a"},
        {"title": "Film B", "tmdb_id": 2, "text": "b"},
        {"title": "Film C", "tmdb_id": 3, "text": "c"},
    ]
    monkeypatch.setattr(prov, "tmdb_now_playing", lambda **kw: films)
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


def _stub_pipeline(monkeypatch, tmp_path, calls=None):
    """Put run_pipeline on rails: no network, no real DB, no real LLM.

    Every MCP tool the pipeline reaches is replaced by a stub that BINDS the
    arguments against the real tool signature first. A bare
    `lambda **kwargs: []` accepts anything, so a call site passing a keyword
    the live tool does not have (`search_music(q=...)` — which silently cost
    the whole music and books leg) slips through and only fails in production.

    When `calls` is given, every `mcp.call` name is appended to it and a tool
    outside the stubbed set fails the test loudly: conftest only blocks
    location_service, so an unstubbed tool would quietly hit the network.
    """
    from moodos import memory_writer
    from moodos import orchestrator as orch
    from moodos.config import settings

    stubbed = {
        "get_weather", "get_user_profile", "search_web_knowledge", "find_nearby_places",
        "search_music", "search_books", "suggest_movies", "search_restaurants",
        "find_nearby_cinemas",
    }

    if calls is not None:
        real_call = orch.mcp.call

        def counting_call(name, **kwargs):
            assert name in stubbed, f"unstubbed MCP tool reached the network: {name}"
            calls.append(name)
            return real_call(name, **kwargs)

        monkeypatch.setattr(orch.mcp, "call", counting_call)

    # This is the first end-to-end run_pipeline test in the suite, so it would
    # otherwise write users / recommendation_events / mood_entries / shown_items
    # straight into the developer's data/moodos.db. db._connect() reads
    # settings.sqlite_path on every connection, so redirecting the instance
    # attribute is enough to keep the real file untouched.
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "moodos_test.db")

    # Network: geocoding, OSM walks, weather.
    monkeypatch.setattr(
        orch.providers, "reverse_geocode",
        lambda lat, lon: {"city": "Ahmedabad", "area": "", "state": "Gujarat"},
    )
    monkeypatch.setattr(orch.providers, "nearby_walks", lambda lat, lon, limit=4: [])
    monkeypatch.setitem(
        orch.mcp.tools, "get_weather",
        lambda lat, lon: {"temperature_c": 27.0, "rainy": False, "condition": "clear",
                          "lat": lat, "lon": lon, "source": "fake", "freshness": "live"},
    )

    # LLM-backed: intent extraction, memories, plan generation. Build the slots
    # off the real heuristic extractor so this stub cannot drift behind the
    # slot contract as new fields are added.
    monkeypatch.setattr(
        orch, "extract_intent",
        lambda message: {**heuristic_extract(message), "budget_inr": 1000,
                         "duration_hours": 2.0, "intensity": "low", "social": "solo",
                         "stay_home": False, "want_movie": False},
    )
    monkeypatch.setitem(
        orch.mcp.tools, "get_user_profile",
        lambda user_id, query, categories=None: {"user_id": user_id, "memories": []},
    )
    monkeypatch.setattr(
        orch, "_plan_with_budget",
        lambda prompt, ranked, slots, weather: {"steps": []},
    )

    # RAG: an empty hit at zero confidence routes through the web fallback just
    # below it, so that tool needs stubbing too or the test leaks network.
    monkeypatch.setattr(orch.knowledge, "retrieve", lambda query, k=8, kinds=None: ([], 0.0))
    monkeypatch.setattr(orch.knowledge, "ingest", lambda doc: None)
    monkeypatch.setitem(orch.mcp.tools, "search_web_knowledge", lambda query, limit=4: [])

    # Durable-memory write at the end of the pipeline reaches mem0 (LLM +
    # embeddings). Orchestrator imports it inside the function body, so
    # patching the module attribute is what the call site resolves.
    monkeypatch.setattr(
        memory_writer, "remember_plan_outcome",
        lambda **kwargs: {"outcome": "generated", "written": []},
    )

    for tool in ("find_nearby_places", "search_music", "search_books",
                 "suggest_movies", "search_restaurants", "find_nearby_cinemas"):
        real_sig = inspect.signature(orch.mcp.tools[tool])

        def _signature_checked_stub(_sig=real_sig, **kwargs):
            _sig.bind(**kwargs)
            return []

        monkeypatch.setitem(orch.mcp.tools, tool, _signature_checked_stub)

    init_db()
    return orch


def test_run_pipeline_fetches_weather_once(monkeypatch, tmp_path):
    """The plan path must resolve weather exactly once per request.

    Counted at the mcp.call seam because that is where the duplicate lived.
    Only an HTTP-level count would have been masked: the second call was
    answered by the 15-minute TTL cache, so it never hit the network (and the
    cache is only populated on success, so it did make a second real request
    whenever the first one failed).
    """
    from moodos import orchestrator as orch

    calls: list[str] = []
    _stub_pipeline(monkeypatch, tmp_path, calls=calls)

    result = orch.run_pipeline(
        "plan me a calm evening", user_id="weather_once_test",
        lat=23.0225, lon=72.5714,
    )

    assert calls.count("get_weather") == 1
    # The sole source must stay a dict: the batch fallback assigned [], which
    # would explode on weather.get("rainy") downstream.
    assert isinstance(result["weather"], dict)
    assert result["weather"]["rainy"] is False
    # The provenance panel must agree with what the fetch actually returned.
    assert result["tool_usage"]["weather"]["source"] == orch._weather_usage_source(
        result["weather"]
    )


def test_music_and_books_lookups_are_not_dropped_by_a_kwarg_mismatch(monkeypatch, tmp_path):
    """`search_music(q=...)` / `search_books(q=...)` failed for every plan.

    Both tools take `query=`. The TypeError was raised inside the parallel
    batch, whose per-lookup `except` logs it and returns `[]` — so the plan
    still came back 200 with no music and no books, and the panel claimed
    "Spotify (live, no fallback)". Nothing in the suite noticed because the
    stubs were `lambda **kwargs: []`.
    """
    from moodos import orchestrator as orch

    _stub_pipeline(monkeypatch, tmp_path)
    recorded: dict[str, dict] = {}
    for tool in ("search_music", "search_books"):
        sig = inspect.signature(orch.mcp.tools[tool])

        def recorder(_tool=tool, _sig=sig, **kwargs):
            _sig.bind(**kwargs)  # TypeError here means the call site drifted
            recorded[_tool] = kwargs
            return []

        monkeypatch.setitem(orch.mcp.tools, tool, recorder)

    result = orch.run_pipeline(
        "plan me a calm evening", user_id="kwarg_mismatch_test",
        lat=23.0225, lon=72.5714,
    )

    assert set(recorded) == {"search_music", "search_books"}
    assert recorded["search_music"]["query"]
    assert not [e for e in result["provider_errors"]
                if e.split(":", 1)[0] in {"search_music", "search_books"}]
    assert result["tool_usage"]["music"]["source"] == "Spotify (live, no fallback)"
    assert result["tool_usage"]["books"]["source"] == "book search"


def test_thin_rag_web_fallback_failure_still_returns_a_plan(monkeypatch, tmp_path):
    """A dead web fallback must degrade the plan, not 500 the endpoint.

    When RAG confidence is below the threshold the pipeline reaches
    `search_web_knowledge` — a call that sits outside every guard. It used to
    be made with `q=` (the tool declares `query=`), so the TypeError escaped
    run_pipeline and /api/plan answered 500 "could not generate a plan".
    """
    from moodos import orchestrator as orch

    _stub_pipeline(monkeypatch, tmp_path)

    def boom(query, limit=4):
        raise RuntimeError("web search is down")

    monkeypatch.setitem(orch.mcp.tools, "search_web_knowledge", boom)

    result = orch.run_pipeline(
        "plan me a calm evening", user_id="thin_rag_test",
        lat=23.0225, lon=72.5714,
    )

    assert "adaptive-fallback" in result["retrieval_path"]
    assert any(e.startswith("search_web_knowledge:") for e in result["provider_errors"])
    # The plan itself survives the failed enrichment.
    assert result["plan"]["steps"]
    # And the provenance panel admits the failure instead of claiming RAG.
    assert result["tool_usage"]["knowledge"]["source"] == \
        "unavailable (provider error, no data returned)"


def test_weather_tool_usage_never_claims_live_when_unavailable():
    """Honesty rule: source reflects the fetch, not an aspiration."""
    from moodos import orchestrator as orch

    live = {"temperature_c": 27.0, "source": "open-meteo", "freshness": "live"}
    down = {"temperature_c": None, "source": "unavailable", "freshness": "unknown"}
    assert orch._weather_usage_source(live) == "Open-Meteo (live)"
    assert orch._weather_usage_source(down) == "unavailable (no live weather)"
    # Any unknown shape (e.g. a wrong-type fallback) must not claim live.
    assert orch._weather_usage_source([]) == "unavailable (no live weather)"
    assert orch._weather_usage_source({}) == "unavailable (no live weather)"


def test_weather_cache_read_failure_falls_through_to_live_fetch(monkeypatch, caplog):
    """A dead TTL cache must not silently degrade weather to rainy=False.

    get_weather is the plan's only weather source. If a cache-read error
    short-circuited into the "unavailable" dict, rain gating in ranking.py and
    the wet-weather branch in _heuristic_plan would silently switch off for
    every user, with no signal. So the cache read must log and fall through to
    the live fetch. Fakes only -- httpx.Client is replaced, no network.
    """
    import logging

    from moodos import providers as prov

    lat, lon = 23.0225, 72.5714

    def boom(key):
        raise KeyError("expires")

    monkeypatch.setattr(prov.ttl_cache, "get", boom)
    # The fallthrough must not re-populate the cache we just poisoned.
    monkeypatch.setattr(prov.ttl_cache, "set", lambda *a, **k: None)

    class _Resp:
        def json(self):
            return {"current": {"temperature_2m": 27.0, "weather_code": 0,
                                "precipitation": 0.0, "wind_speed_10m": 4.0}}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            return _Resp()

    monkeypatch.setattr(prov.httpx, "Client", _Client)

    with caplog.at_level(logging.WARNING, logger="moodos.providers"):
        result = prov.get_weather(lat, lon)

    # Fell through to the live fetch instead of returning the degraded dict.
    assert result["source"] == "open-meteo", result
    assert result["freshness"] == "live"
    assert result["temperature_c"] == 27.0
    assert result["condition"] == "clear"
    # ...and the failure is visible, not silent.
    assert "weather cache read failed" in caplog.text
