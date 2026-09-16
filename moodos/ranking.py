from __future__ import annotations

import re
from typing import Any

# Titles the provider fallbacks fabricate when OSM has no real venue name.
# These are not real places and never make useful plan steps.
_PLACEHOLDER_RE = re.compile(
    r"^nearby (cafe|coffee|restaurant|food|fast food|ice cream|"
    r"parlour|park|cinema|theatre|theater|place)$",
    re.I,
)


WEIGHTS = {
    "mood": 0.28,
    "preference": 0.22,
    "context": 0.16,
    "review": 0.12,
    "cross": 0.10,
    "novelty": 0.08,
    "distance": 0.12,
    "food": 0.20,
}

# Conceptual only — not frozen forever; can be learned from ranking logs later.


def _mood_match(item: dict, slots: dict) -> float:
    intensity = (slots.get("intensity") or "low").lower()
    item_int = (item.get("intensity") or "low").lower()
    if intensity == "low" and item_int == "high":
        return 0.05
    if intensity == "low" and item_int == "low":
        return 0.95
    moods = " ".join(item.get("moods", []) + [item.get("text", ""), item.get("title", "")]).lower()
    desired = (slots.get("desired_mood") or "").lower()
    current = (slots.get("current_mood") or "").lower()
    score = 0.5
    if desired and desired in moods:
        score += 0.3
    if "exhaust" in current and any(w in moods for w in ("calm", "quiet", "gentle", "comfort", "relax")):
        score += 0.2
    return min(score, 1.0)


def _pref_match(item: dict, memories: list[dict], preferences: dict | None = None) -> float:
    blob = (item.get("title", "") + " " + item.get("text", "")).lower()
    score = 0.5
    for mem in memories or []:
        t = mem["text"].lower()
        if "quiet cafe" in t and item.get("kind") in {"place", "food"} and "quiet" in blob:
            score += 0.2
        if "movie" in t and item.get("kind") == "movie":
            score += 0.15
        if "crowd" in t and item.get("crowded"):
            score -= 0.4
        if "budget" in t and (item.get("estimated_cost") or 0) <= 350:
            score += 0.1
    # Structured preference signals (learned from happy reactions) give a SMALL,
    # bounded nudge — mood/budget/distance still dominate the weighted score.
    signals = preferences or {}
    if item.get("kind") == "movie":
        code = str(item.get("original_language") or "").lower()
        if signals.get("movie_language_code") and code and code == signals["movie_language_code"]:
            score += 0.15
        genres = " ".join(item.get("genres") or []).lower()
        if genres and any(g and g in genres for g in signals.get("movie_genres") or []):
            score += 0.08
    cuisine = str(item.get("cuisine") or "").lower()
    if cuisine and signals.get("cuisine") and signals["cuisine"] in cuisine:
        score += 0.12
    return max(0.0, min(score, 1.0))


def hard_filter(item: dict, slots: dict, weather: dict, remaining_budget: float, remaining_min: float) -> bool:
    title = (item.get("title") or "").strip()
    if not title or _PLACEHOLDER_RE.match(title):
        return False  # unnamed / placeholder venue — no real place data
    cost = float(item.get("estimated_cost") or 0)
    dur = float(item.get("duration_min") or 0)
    if cost > remaining_budget:
        return False
    if dur > remaining_min:
        return False
    if item.get("likely_closed_at"):
        return False
    if (slots.get("intensity") or "").lower() == "low" and (item.get("intensity") or "") == "high":
        return False
    if item.get("crowded") and (slots.get("social") == "solo"):
        return False
    if weather.get("rainy") and item.get("outdoor") and item.get("kind") == "place" and item.get("needs_clear_weather"):
        return False
    dist = item.get("distance_km")
    kind = item.get("kind")
    if dist is not None and kind in {"place", "food"} and dist > 8:
        return False
    if dist is not None and kind == "movie" and item.get("has_venue") and dist > 20:
        return False
    return True


def _food_emphasis(item: dict, slots: dict) -> float:
    """Extra score when the user explicitly made food the main thing.

    A food-priority user wants the meal to be the point of the outing. When
    there is also meaningful budget headroom we prefer a substantial sit-down
    restaurant (mid/premium tier) over a cheap quick stop, so the planner
    doesn't default to e.g. a ₹150 dairy-parlour snack while leaving a large
    budget unspent."""
    if not slots.get("food_priority"):
        return 0.0
    subtype = item.get("subtype")
    kind = item.get("kind")
    is_food = kind in {"food", "place"} or subtype in {"restaurant", "fast_food", "cafe", "ice_cream"}
    if not is_food:
        return 0.0
    budget = float(slots.get("budget_inr") or 1000)
    cost = float(item.get("estimated_cost") or 0)
    tier = str(item.get("price_tier") or "budget")
    substantial = subtype == "restaurant" or tier in {"mid", "premium"}
    if substantial and budget >= 800 and cost > 0 and cost <= budget:
        return 0.75
    if substantial:
        return 0.45
    return 0.35


def score_item(item: dict, slots: dict, memories: list[dict], weather: dict,
               preferences: dict | None = None) -> float:
    mood = _mood_match(item, slots)
    pref = _pref_match(item, memories, preferences)
    ctx = 0.7
    if weather.get("rainy") and not item.get("outdoor"):
        ctx += 0.15
    if slots.get("social") == "solo" and not item.get("crowded"):
        ctx += 0.1
    review = float(item.get("review_quality") or item.get("vote") or 6) / 10.0
    review = min(max(review, 0.3), 1.0)
    cross = float(item.get("cross_domain") or 0.6)
    novelty = float(item.get("novelty") or 0.5)
    dist = item.get("distance_km")
    dist_pen = min(float(dist) / 12.0, 1.0) if dist is not None else 0.15
    return (
        WEIGHTS["mood"] * mood
        + WEIGHTS["preference"] * pref
        + WEIGHTS["context"] * min(ctx, 1.0)
        + WEIGHTS["review"] * review
        + WEIGHTS["cross"] * cross
        + WEIGHTS["novelty"] * novelty
        + WEIGHTS["food"] * _food_emphasis(item, slots)
        - WEIGHTS["distance"] * dist_pen
    )


def rerank(items: list[dict]) -> list[dict]:
    seen_kinds = []
    out = []
    rest = []
    for item in items:
        kind = item.get("kind")
        if kind not in seen_kinds:
            out.append(item)
            seen_kinds.append(kind)
        else:
            rest.append(item)
    return out + rest
