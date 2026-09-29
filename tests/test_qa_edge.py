"""QA/edge-case coverage for plan consistency: durations, music length,
budget flags, and extreme inputs. No network required."""

from moodos.orchestrator import (
    _DUR_CAPS,
    _assemble_plan,
    _attach_music_tracks,
    _heuristic_plan,
)

_LAT, _LON = 23.0225, 72.5714

_CAFE = {
    "id": "osm:c1", "kind": "place", "subtype": "cafe",
    "title": "Cafe One", "lat": 23.0228, "lon": 72.5719,
    "estimated_cost": 120, "duration_min": 45,
    "intensity": "low", "crowded": False, "distance_km": 0.1,
    "final_score": 0.86,
}


def _slots(**over):
    base = {
        "current_mood": "exhausted", "desired_mood": "relaxed",
        "intensity": "low", "social": "solo", "budget_inr": 1000,
        "duration_hours": 2.0, "music_language": None,
        "food_priority": False, "stay_home": False, "want_movie": False,
    }
    base.update(over)
    return base


def _plan(steps):
    return {
        "steps": steps,
        "total_duration_min": int(sum(int(s.get("duration_min") or 0) for s in steps)),
        "total_cost_inr": int(sum(int(s.get("cost_inr") or 0) for s in steps)),
    }


# ---------------------------------------------------------------------------
# MUSIC
# ---------------------------------------------------------------------------

def test_music_step_duration_equals_real_track_sum():
    music = [
        {"id": f"s{i}", "title": f"Track {i}", "kind": "music",
         "duration_sec": 210 + i * 5}
        for i in range(9)
    ]
    plan = {
        "steps": [{"kind": "music", "title": "Wind down", "duration_min": 30}],
        "total_duration_min": 30, "total_cost_inr": 0,
        "requested_minutes": 120, "budget_fit": {"tolerance_min": 4},
    }
    _attach_music_tracks(plan, music)
    step = plan["steps"][0]
    real_sec = sum(int(t.get("duration_sec") or 0) for t in step["tracks"])
    assert step["playlist_duration_min"] == round(real_sec / 60, 1)
    assert step["duration_min"] == max(1, int(round(real_sec / 60)))
    assert plan["total_duration_min"] == step["duration_min"]


def test_music_step_respects_duration_cap_in_assembly():
    slots = _slots(duration_hours=5.0)
    plan = _plan([
        {"order": 1, "kind": "cafe", "title": "Cafe One",
         "duration_min": 45, "cost_inr": 120, "flexible": True},
        {"order": 2, "kind": "music", "title": "Wind down",
         "duration_min": 20, "cost_inr": 0, "flexible": True},
    ])
    result = _assemble_plan(
        plan, [_CAFE], slots, _LAT, _LON, [], weather={"rainy": False}
    )
    music = next(s for s in result["steps"] if s.get("kind") == "music")
    assert music["duration_min"] <= _DUR_CAPS["music"]


def test_music_attach_totals_consistent_after_reclaim():
    # Music target is 30 min but only 3 short tracks exist (12 min real) —
    # the plan must not end up silently short: a flexible step absorbs the gap.
    music = [
        {"id": f"s{i}", "title": f"Track {i}", "kind": "music",
         "duration_sec": 240}
        for i in range(3)
    ]
    plan = {
        "steps": [
            {"kind": "cafe", "title": "Cafe One", "duration_min": 60,
             "cost_inr": 0, "flexible": True},
            {"kind": "music", "title": "Wind down", "duration_min": 30,
             "cost_inr": 0, "flexible": True},
        ],
        "total_duration_min": 90, "total_cost_inr": 0,
        "requested_minutes": 90, "budget_fit": {"tolerance_min": 3},
    }
    _attach_music_tracks(plan, music)
    assert plan["total_duration_min"] >= 85  # 3 tracks ≈ 12 min + 60 cafe + reclaim ea
    assert plan["total_duration_min"] == int(
        sum(int(s.get("duration_min") or 0) for s in plan["steps"])
    )


# ---------------------------------------------------------------------------
# BUDGET
# ---------------------------------------------------------------------------

def test_budget_status_flags_over_budget():
    slots = _slots(budget_inr=200)
    plan = _plan([
        {"order": 1, "kind": "cafe", "title": "Cafe One",
         "duration_min": 45, "cost_inr": 250, "flexible": True},
    ])
    result = _assemble_plan(
        plan, [_CAFE], slots, _LAT, _LON, [], weather={"rainy": False}
    )
    assert result["budget"]["over_budget"] is True
    assert result["budget"]["excess_inr"] >= 50
    assert result["budget"]["budget_inr"] == 200
    assert result["budget"]["total_cost_inr"] == result["total_cost_inr"]


def test_budget_status_within_budget():
    slots = _slots(budget_inr=200)
    plan = _plan([
        {"order": 1, "kind": "cafe", "title": "Cafe One",
         "duration_min": 45, "cost_inr": 80, "flexible": True},
    ])
    result = _assemble_plan(
        plan, [_CAFE], slots, _LAT, _LON, [], weather={"rainy": False}
    )
    assert result["budget"]["over_budget"] is False
    assert result["budget"]["percent_used"] == 40.0


def test_budget_zero_treated_as_real_zero():
    slots = _slots(budget_inr=0)
    plan = _plan([
        {"order": 1, "kind": "cafe", "title": "Cafe One",
         "duration_min": 45, "cost_inr": 120, "flexible": True},
    ])
    result = _assemble_plan(
        plan, [_CAFE], slots, _LAT, _LON, [], weather={"rainy": False}
    )
    assert result["budget"]["over_budget"] is True
    assert result["budget"]["budget_inr"] == 0
    assert result["budget"]["percent_used"] == 100.0


# ---------------------------------------------------------------------------
# EXTREME DURATIONS / EMPTY INPUTS
# ---------------------------------------------------------------------------

def test_extreme_durations_no_crash_budget_fit_present():
    for hours in (0.5, 24.0):
        slots = _slots(duration_hours=hours)
        plan = _plan([
            {"order": 1, "kind": "cafe", "title": "Cafe One",
             "duration_min": 45, "cost_inr": 120, "flexible": True},
            {"order": 2, "kind": "music", "title": "Wind down",
             "duration_min": 20, "cost_inr": 0, "flexible": True},
        ])
        result = _assemble_plan(
            plan, [_CAFE], slots, _LAT, _LON, [], weather={"rainy": False}
        )
        assert isinstance(result["total_duration_min"], int)
        assert result["budget_fit"]["requested_min"] == int(hours * 60)
        total = sum(int(s.get("duration_min") or 0) for s in result["steps"])
        assert total == result["total_duration_min"]


def test_heuristic_empty_pool_empty_plan():
    slots = _slots()
    plan = _heuristic_plan([], slots, {"rainy": False})
    assert plan["steps"] == []
    assert plan["total_cost_inr"] == 0


def test_heuristic_missing_weather():
    slots = _slots()
    plan = _heuristic_plan([], slots, {})
    assert "steps" in plan
    assert "explanation" in plan