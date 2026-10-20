"""Group budgets: "Rs5000 for 5 friends" is a group TOTAL, not Rs5000 for one.

The pipeline now extracts a party_size slot and every cost decision scales
per-person price estimates by it, so a group outing spends (and is filtered
against) the whole group budget. Solo messages keep party_size=None -> 1,
so nothing changes for the single-person path.
"""

from moodos import memory_writer as mw
from moodos import nlu
from moodos.ranking import hard_filter, party_size
from moodos.orchestrator import _heuristic_plan


# ----------------------------------------------------------- extraction


def test_heuristic_extracts_party_size_for_friends():
    slots = nlu.heuristic_extract("plan dinner, Rs5000 for 5 friends")
    assert slots["budget_inr"] == 5000
    assert slots["party_size"] == 5


def test_heuristic_extracts_party_size_phrasings():
    assert nlu.heuristic_extract("movie night for the 4 of us")["party_size"] == 4
    assert nlu.heuristic_extract("a group of 6 people")["party_size"] == 6


def test_solo_message_has_no_party_size():
    slots = nlu.heuristic_extract("I'm exhausted, have 1000 rupees, four hours")
    assert slots["budget_inr"] == 1000
    assert slots["party_size"] is None
    assert party_size(slots) == 1


def test_party_size_from_llm_when_heuristic_misses(monkeypatch):
    # "between us" has no count for the regex; the LLM fills it in.
    monkeypatch.setattr(
        nlu.router, "extract_json",
        lambda prompt: {"party_size": 3, "budget_inr": 2000},
    )
    slots = nlu.extract_intent("dinner between us, 2000 rupees total")
    assert slots["party_size"] == 3


def test_heuristic_party_size_wins_over_llm(monkeypatch):
    monkeypatch.setattr(nlu.router, "extract_json", lambda prompt: {"party_size": 9})
    slots = nlu.extract_intent("Rs5000 for 5 friends")
    assert slots["party_size"] == 5  # the explicit count is authoritative


def test_party_size_helper_is_defensive():
    assert party_size({}) == 1
    assert party_size({"party_size": None}) == 1
    assert party_size({"party_size": "garbage"}) == 1
    assert party_size({"party_size": 4.7}) == 4
    assert party_size({"party_size": 999}) == 50  # clamped


# ----------------------------------------------------------- cost scaling


def _item(title, cost, kind="food", **extra):
    return {"title": title, "estimated_cost": cost, "kind": kind,
            "duration_min": 60, **extra}


def test_hard_filter_uses_group_cost_for_group_budget():
    slots = {"budget_inr": 5000, "party_size": 5, "intensity": "medium"}
    weather = {"rainy": False}
    # Per-person 1200 x 5 = 6000 > 5000 -> filtered for the group...
    assert hard_filter(_item("Premium restaurant", 1200, "food"), slots, weather, 5000, 600) is False
    # ...but the same item fits when the budget is what one person has.
    solo = dict(slots, party_size=None)
    assert hard_filter(_item("Premium restaurant", 1200, "food"), solo, weather, 5000, 600) is True
    # A per-person 450 -> group 2250 fits the 5000 group budget.
    assert hard_filter(_item("Casual restaurant", 450, "food"), slots, weather, 5000, 600) is True


def test_heuristic_plan_costs_are_group_totals():
    slots = {"budget_inr": 5000, "party_size": 5, "duration_hours": 4,
             "intensity": "medium"}
    ranked = [
        {"title": "The Gyan Cafe", "kind": "food", "subtype": "restaurant",
         "estimated_cost": 350, "duration_min": 60, "cuisine": "Gujarati"},
        {"title": "Quiet Park", "kind": "place", "subtype": "walk",
         "estimated_cost": 0, "duration_min": 20, "outdoor": True},
        {"title": "A Film", "kind": "movie", "estimated_cost": 220,
         "duration_min": 130, "tmdb_id": 7},
    ]
    plan = _heuristic_plan(ranked, slots, {"rainy": False})
    costs = {s["kind"]: s["cost_inr"] for s in plan["steps"]}
    # Restaurant: min(budget, 350x5) = 1750 — the 500 cap scales to 500x5.
    assert costs["restaurant"] == 1750
    # Movie ticket: 220 per head x 5.
    assert costs["movie"] == 1100
    assert plan["total_cost_inr"] == 1750 + 1100
    assert plan["total_cost_inr"] <= 5000


def test_heuristic_plan_solo_costs_unchanged():
    slots = {"budget_inr": 1000, "duration_hours": 4, "intensity": "medium"}
    ranked = [
        {"title": "The Gyan Cafe", "kind": "food", "subtype": "restaurant",
         "estimated_cost": 350, "duration_min": 60, "cuisine": "Gujarati"},
        {"title": "A Film", "kind": "movie", "estimated_cost": 220,
         "duration_min": 130, "tmdb_id": 7},
    ]
    plan = _heuristic_plan(ranked, slots, {"rainy": False})
    costs = {s["kind"]: s["cost_inr"] for s in plan["steps"]}
    assert costs["restaurant"] == 350  # 500 cap still applies solo
    assert costs["movie"] == 220


# ---------------------------------------------------- durable preferences


def test_durable_budget_fact_is_per_head_for_groups():
    facts = mw.extract_durable_facts(
        "Rs5000 for 5 friends",
        {"budget_inr": 5000, "party_size": 5},
    )
    budget = next(f for f in facts if f["kind"] == "budget")
    assert "₹1000 per person" in budget["text"]
    assert "mid band" in budget["text"]  # 1000/head, not 5000 -> premium


def test_durable_budget_fact_solo_text_unchanged():
    facts = mw.extract_durable_facts("budget 5000", {"budget_inr": 5000})
    budget = next(f for f in facts if f["kind"] == "budget")
    assert budget["text"] == "Comfortable spending around ₹5000 on an evening out (premium band)"
