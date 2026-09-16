import pytest
from fastapi.testclient import TestClient

from app import app
from moodos import journal as journalmod
from moodos import memory_writer as mw
from moodos.db import init_db, save_event
from moodos.memory import mem0
from moodos.orchestrator import (
    _derive_search_query,
    _normalize_movie_steps,
    _preference_signals,
)
from moodos.ranking import score_item

init_db()

USER = "pref_test"
USER_API = "pref_api_test"


@pytest.fixture(autouse=True)
def clean_mem(monkeypatch):
    # Keep the preference tests hermetic + fast: never touch the real Mem0
    # cloud even when a live API key is configured in settings.
    monkeypatch.setattr(mem0, "cloud", None)
    mem0.delete(USER)
    mem0.delete(USER_API)
    journalmod.clear_journal(USER_API)
    yield
    mem0.delete(USER)
    mem0.delete(USER_API)
    journalmod.clear_journal(USER_API)


HAPPY_MOVIE_PLAN = {
    "steps": [
        {"kind": "movie", "original_language": "hi", "genres": ["Comedy", "Drama"],
         "mood_fit_verified": True},
        {"kind": "cafe", "title": "The Gyan Cafe"},
        {"kind": "restaurant", "title": "Main Dish (Italian, Pizza)"},
        {"kind": "music", "title": "Calm playlist"},
    ]
}


def test_extract_reaction_facts_happy_plan():
    slots = {"music_language": "punjabi", "music_language_explicit": True}
    texts = [f["text"] for f in mw.extract_reaction_facts(HAPPY_MOVIE_PLAN, slots)]
    assert "Prefers Hindi-language movies" in texts
    assert any("Comedy" in t for t in texts)
    assert "Likes quiet cafes" in texts
    assert "Enjoys italian food" in texts
    assert "Enjoys Punjabi music" in texts


def test_locale_inferred_music_not_learned():
    plan = {"steps": [{"kind": "music", "title": "Calm playlist"}]}
    slots = {"music_language": "hindi", "music_language_explicit": False}
    assert mw.extract_reaction_facts(plan, slots) == []


def test_learn_local_store_then_reinforce_not_duplicate():
    plan = {"steps": [{"kind": "movie", "original_language": "hi",
                       "genres": ["Comedy"], "mood_fit_verified": True}]}
    r1 = mw.learn_from_reaction(USER, plan, {}, entry_id=1)
    assert r1["learned"] == 2
    rows = mem0.local.list(USER)
    assert len(rows) == 2  # movie language + genre, no duplicates

    r2 = mw.learn_from_reaction(USER, plan, {}, entry_id=2)
    assert r2["learned"] == 0
    assert all(w["action"] == "dup" and w.get("reinforced") for w in r2["written"])
    assert len(mem0.local.list(USER)) == 2  # still two memories, not four

    mlang = next(r for r in mem0.local.list(USER) if r["text"] == "Prefers Hindi-language movies")
    assert mlang["metadata"]["reinforced_count"] == 1
    assert round(mlang["confidence"], 2) == 0.83  # 0.75 + one 0.08 bump


def test_preference_signals_parse():
    memories = [
        {"text": "Prefers Hindi-language movies"},
        {"text": "Enjoys Comedy movies"},
        {"text": "Enjoys Punjabi music"},
        {"text": "Enjoys Italian food"},
    ]
    sig = _preference_signals(memories)
    assert sig["movie_language"] == "hindi"
    assert sig["movie_language_code"] == "hi"
    assert sig["movie_genres"] == ["comedy"]
    assert sig["music_language"] == "punjabi"
    assert sig["cuisine"] == "italian"


def test_preference_signals_ignores_ambiguous_text():
    # Bootstrap-style prose must NOT produce structured signals.
    sig = _preference_signals([
        {"text": "The user prefers budget-friendly experiences, enjoys movies"},
    ])
    assert sig["movie_language"] is None
    assert sig["movie_genres"] == []
    assert sig["music_language"] is None


def test_movie_query_biased_by_preferences():
    q = _derive_search_query(
        "plan an evening",
        {},
        "movie",
        {"movie_language": "hindi", "movie_genres": ["comedy"]},
    )
    assert "hindi" in q and "comedy" in q
    # Explicit genre in the message still wins over the stored preference.
    q2 = _derive_search_query(
        "I want a drama film",
        {},
        "movie",
        {"movie_genres": ["comedy"]},
    )
    assert "drama" in q2 and "comedy" not in q2


def test_normalize_movie_steps_carries_language():
    plan = {"steps": [{"kind": "movie", "title": "The Lunchbox"}]}
    ranked = [{
        "kind": "movie", "title": "The Lunchbox", "original_language": "hi",
        "runtime_min_real": 124, "duration_min": 124, "venue": "PVR", "tmdb_id": None,
        "showtime_estimated": True, "showtime_disclaimer": "check venue",
        "genres": ["Comedy"], "genre_source": "tmdb", "genre_fit": "good",
        "mood_fit_verified": True,
    }]
    _normalize_movie_steps(plan, ranked)
    step = plan["steps"][0]
    assert step["original_language"] == "hi"
    assert step["genres"] == ["Comedy"]
    assert step["mood_fit_verified"] is True


def test_score_item_small_preference_bonus():
    item = {"title": "Film", "kind": "movie", "original_language": "hi",
            "genres": ["Comedy"], "review_quality": 6, "intensity": "low",
            "estimated_cost": 150, "distance_km": 0.5}
    slots = {"intensity": "low", "budget_inr": 1000, "duration_hours": 4}
    liked = score_item(item, slots, [], {"rainy": False},
                       {"movie_language_code": "hi", "movie_genres": ["comedy"]})
    other = score_item(item, slots, [], {"rainy": False},
                       {"movie_language_code": "en"})
    assert liked > other + 0.04
    assert liked <= 1.0  # bounded nudge


def test_react_endpoint_learns_on_happy_not_sad():
    event_id = save_event(USER_API, "watch a movie", {
        "plan": {"steps": [{"kind": "movie", "original_language": "hi",
                            "genres": ["Comedy"], "mood_fit_verified": True}]},
        "slots": {},
    })
    entry_id = journalmod.log_mood_entry(
        USER_API, {"current_mood": "tired"},
        plan={"steps": []}, event_id=event_id,
    )
    client = TestClient(app)
    res = client.post("/api/journal/react", json={
        "user_id": USER_API, "entry_id": entry_id, "reaction": "happy",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["applied"] is True
    assert data["learned"]["learned"] == 2

    # A sad reaction must NOT learn preferences.
    entry_id2 = journalmod.log_mood_entry(
        USER_API, {"current_mood": "tired"},
        plan={"steps": []}, event_id=event_id,
    )
    res2 = client.post("/api/journal/react", json={
        "user_id": USER_API, "entry_id": entry_id2, "reaction": "sad",
    })
    assert res2.status_code == 200
    assert res2.json()["learned"] is None