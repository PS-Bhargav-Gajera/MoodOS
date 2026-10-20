"""Unit tests for moodos.chat — the short-answer chat mode.

Nothing here went through a test before: test_pipeline only asserted
classify_turn (nlu), and its answer_chat route test stubbed handle_message
entirely, so live_facts and every reply helper were untested.

All provider/network seams are stubbed (conftest blocks real HTTP anyway);
these tests pin the reply copy and the topic routing contract.
"""

import pytest

from moodos import chat as chatmod
from moodos import memory as memorymod
from moodos import providers
from moodos.config import settings
from moodos.memory import mem0

USER = "chat_test_user"


@pytest.fixture(autouse=True)
def offline_facts(monkeypatch, tmp_path):
    """Deterministic place/weather, local-only memory, isolated store."""
    monkeypatch.setattr(mem0, "cloud", None)
    monkeypatch.setattr(memorymod, "MEM_PATH", tmp_path / "mem0_users.json")
    monkeypatch.setattr(
        providers, "reverse_geocode",
        lambda lat, lon: {"city": "Ahmedabad", "suburb": "Navrangpura",
                          "display_name": "Navrangpura, Ahmedabad, India"},
    )
    monkeypatch.setattr(
        providers, "get_weather",
        lambda lat, lon: {"temperature_c": 28, "condition": "clear",
                          "rainy": False, "source": "open-meteo"},
    )
    mem0.delete(USER)
    yield
    mem0.delete(USER)


# ------------------------------------------------------------- live_facts


def test_live_facts_marks_default_location():
    facts = chatmod.live_facts(USER, None, None)
    assert facts["used_default_location"] is True
    assert facts["lat"] == settings.default_lat


def test_live_facts_passes_through_coords_and_merges_names():
    facts = chatmod.live_facts(USER, 22.0, 72.0, {"city": "Surat"})
    assert facts["used_default_location"] is False
    assert facts["lat"] == 22.0
    assert facts["place"]["city"] == "Surat"  # explicit name wins over geocode
    assert facts["place"]["suburb"] == "Navrangpura"  # untouched keys survive


def test_live_facts_unavailable_weather_is_honest(monkeypatch):
    monkeypatch.setattr(
        providers, "get_weather",
        lambda lat, lon: {"temperature_c": None, "condition": "unknown",
                          "rainy": False, "source": "unavailable"},
    )
    facts = chatmod.live_facts(USER, 22.0, 72.0)
    assert facts["weather"]["source"] == "unavailable"


# ----------------------------------------------------------- reply helpers


def test_location_reply_shows_coords():
    facts = {"place": {"city": "Ahmedabad"}, "lat": 23.0225, "lon": 72.5714,
             "used_default_location": False}
    reply = chatmod._location_reply(facts)
    assert "You are near Ahmedabad" in reply
    assert "23.0225" in reply
    assert "don't have your live GPS" not in reply


def test_location_reply_flags_default_location():
    facts = {"place": {"city": "Ahmedabad"}, "lat": 23.0, "lon": 72.0,
             "used_default_location": True}
    reply = chatmod._location_reply(facts)
    assert reply.startswith("I don't have your live GPS yet")


def test_weather_reply_live_and_unavailable():
    live = chatmod._weather_reply({
        "place": {"city": "Ahmedabad"},
        "weather": {"temperature_c": 28, "condition": "clear", "rainy": False},
    })
    assert "28°C" in live and "clear" in live

    down = chatmod._weather_reply({
        "place": {"city": "Ahmedabad"},
        "weather": {"temperature_c": None, "condition": "unknown"},
    })
    assert down == "I could not fetch live weather for Ahmedabad."

    rainy = chatmod._weather_reply({
        "place": {"city": "Ahmedabad"},
        "weather": {"temperature_c": 24, "condition": "rain", "rainy": True},
    })
    assert "raining" in rainy


def test_memory_reply_with_and_without_memories():
    empty = chatmod._memory_reply({"memories": []})
    assert "don't have lasting preferences" in empty

    full = chatmod._memory_reply({"memories": ["Likes quiet cafes", "Enjoys movies"]})
    assert "Likes quiet cafes" in full and "Enjoys movies" in full


def test_help_reply_mentions_planning():
    assert "mood, budget, time" in chatmod._help_reply()


# ------------------------------------------------------------- answer_chat


def test_answer_chat_routes_location_topic():
    out = chatmod.answer_chat("what is my curr location", USER, 23.0, 72.0)
    assert out["mode"] == "chat"
    assert out["topic"] == "location"
    assert out["plan"] is None
    assert "You are near" in out["reply"]
    assert out["used_default_location"] is False


def test_answer_chat_routes_weather_topic():
    out = chatmod.answer_chat("what's the weather?", USER, 23.0, 72.0)
    assert out["topic"] == "weather"
    assert "28°C" in out["reply"]
    assert out["weather"]["temperature_c"] == 28


def test_answer_chat_routes_memory_topic():
    mem0.add(USER, "Likes quiet cafes", category="preference")
    out = chatmod.answer_chat("remember me", USER, 23.0, 72.0)
    assert out["topic"] == "memory"
    assert "Likes quiet cafes" in out["reply"]


def test_answer_chat_routes_help_topic():
    out = chatmod.answer_chat("help", USER, 23.0, 72.0)
    assert out["topic"] == "help"
    assert "Ask a short question" in out["reply"]


def test_answer_chat_other_topic_uses_llm(monkeypatch):
    seen = {}

    def fake_extract(prompt):
        seen["prompt"] = prompt
        return {"reply": "  A calm evening suits you.  "}

    monkeypatch.setattr(chatmod.router, "extract_json", fake_extract)
    out = chatmod.answer_chat("tell me a joke?", USER, 23.0, 72.0)
    assert out["topic"] == "other"
    assert out["reply"] == "A calm evening suits you."  # stripped
    assert "tell me a joke?" in seen["prompt"]


def test_answer_chat_llm_empty_falls_back_to_help(monkeypatch):
    monkeypatch.setattr(chatmod.router, "extract_json", lambda prompt: {})
    out = chatmod.answer_chat("tell me a joke?", USER, 23.0, 72.0)
    assert out["reply"] == chatmod._help_reply()
