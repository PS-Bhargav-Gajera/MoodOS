"""D2: no repeated stops inside a single plan."""

from moodos.orchestrator import _assemble_plan, _norm_title, _remove_duplicate_stops


def _stop(title, kind="place", subtype="cafe", dur=45):
    return {"order": 0, "kind": kind, "subtype": subtype, "title": title,
            "duration_min": dur, "cost_inr": 120, "flexible": True,
            "why": "a stop", "lat": 23.0225, "lon": 72.5714}


def _music(title="Chill wind-down mix"):
    return {"order": 0, "kind": "music", "title": title, "duration_min": 20,
            "cost_inr": 0, "flexible": True, "why": "wind down"}


def _slots():
    return {"current_mood": "exhausted", "desired_mood": "relaxed", "intensity": "low",
            "social": "solo", "budget_inr": 1000, "duration_hours": 3.0,
            "music_language": None, "food_priority": False, "stay_home": False,
            "want_movie": False}


def test_remove_duplicate_stops_keeps_first_and_notes():
    plan = {"steps": [
        _stop("Scoop N Munch"), _stop("Law Canteen(F2)", "food", "restaurant", 60),
        _stop("Scoop N Munch"), _stop("Law Canteen(F2)", "food", "restaurant", 60),
        _music(),
    ]}
    plan = _remove_duplicate_stops(plan, notes := [])
    titles = [s["title"] for s in plan["steps"]]
    assert titles == ["Scoop N Munch", "Law Canteen(F2)", "Chill wind-down mix"], titles
    assert len(notes) == 2, notes
    assert notes[0] == "Removed a repeated stop (Scoop N Munch) so every stop in your plan is different."
    assert notes[1] == "Removed a repeated stop (Law Canteen(F2)) so every stop in your plan is different."


def test_assemble_plan_drops_repeats_and_rebuilds_travel():
    plan = {"steps": [
        _stop("Scoop N Munch"), _stop("Law Canteen(F2)", "food", "restaurant", 60),
        _stop("Scoop N Munch"), _stop("Law Canteen(F2)", "food", "restaurant", 60),
        _music(),
    ], "total_duration_min": 0, "total_cost_inr": 0}
    ranked = [
        {"id": "osm:c1", "kind": "place", "subtype": "cafe", "title": "Scoop N Munch",
         "lat": 23.0228, "lon": 72.5719, "estimated_cost": 120, "duration_min": 45,
         "intensity": "low", "crowded": False, "distance_km": 0.1, "final_score": 0.86},
        {"id": "osm:r2", "kind": "food", "subtype": "restaurant", "title": "Law Canteen(F2)",
         "lat": 23.0231, "lon": 72.5722, "estimated_cost": 200, "duration_min": 60,
         "intensity": "low", "crowded": False, "distance_km": 0.2, "final_score": 0.80},
    ]
    out = _assemble_plan(plan, ranked, _slots(), 23.0225, 72.5714, [],
                         weather={"rainy": False})

    stops = [s for s in out["steps"] if s["kind"] != "travel"]
    travel = [s for s in out["steps"] if s["kind"] == "travel"]
    titles = [s["title"] for s in stops]
    # The three real stops survive, in order; the budget loop may append a
    # small rest buffer, but no venue title appears twice.
    assert titles[:3] == ["Scoop N Munch", "Law Canteen(F2)", "Chill wind-down mix"], titles
    assert len({t for t in titles}) == len(titles), titles
    assert len(out["budget_notes"]) == 2, out["budget_notes"]
    assert _norm_title("Scoop N Munch") in {_norm_title(t) for t in titles}
    # Travel legs connect only the remaining physical stops. Music is not a
    # physical stop, so the single physical pair yields exactly one leg — and
    # it must not mention a dropped repeat.
    physical = [s["title"] for s in stops if s["kind"] in
                {"place", "food", "cafe", "restaurant", "movie", "streaming", "indoor"}]
    assert physical == ["Scoop N Munch", "Law Canteen(F2)"], physical
    assert len(travel) == len(physical) - 1, [s["title"] for s in travel]
    for leg in travel:
        assert leg.get("from") in physical and leg.get("to") in physical, leg
    assert "Scoop N Munch" not in [leg.get("to") for leg in travel][1:], \
        "second visit to Scoop N Munch survived"
