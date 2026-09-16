from __future__ import annotations

from typing import Any

from moodos.config import settings
from moodos.llm import router
from moodos.memory import mem0
from moodos.nlu import classify_turn
from moodos import providers

CHAT_PROMPT = """You are MoodOS, a concise assistant.
Answer the user in 1-3 short sentences. Use ONLY the live facts below.
Do not invent a full outing plan. Do not add extra sections.
If the facts don't contain the answer, say you don't have that live data.
Facts:
{facts}
User:
{message}
Return JSON: {{"reply": "..."}}
"""


def live_facts(user_id: str, lat: float | None, lon: float | None,
               location_names: dict | None = None) -> dict[str, Any]:
    used_default = lat is None or lon is None
    lat = lat if lat is not None else settings.default_lat
    lon = lon if lon is not None else settings.default_lon
    place = providers.reverse_geocode(lat, lon)
    if location_names:
        for _k in ("city", "area", "state", "country", "display_name"):
            if location_names.get(_k):
                place = {**place, _k: location_names[_k]}
    weather = providers.get_weather(lat, lon)
    memories = [m.get("text") for m in mem0.retrieve(user_id, "preferences", k=6)]
    return {
        "used_default_location": used_default,
        "lat": lat,
        "lon": lon,
        "place": place,
        "weather": weather,
        "memories": memories,
    }


def _location_reply(facts: dict) -> str:
    place = facts.get("place") or {}
    city = place.get("city") or settings.default_city
    suburb = place.get("suburb")
    where = f"{suburb}, {city}" if suburb else city
    extra = place.get("display_name")
    prefix = ""
    if facts.get("used_default_location"):
        prefix = "I don't have your live GPS yet (allow location in the browser). Using the default city. "
    line = f"You are near {where} ({facts['lat']:.4f}°N, {facts['lon']:.4f}°E)."
    if extra and extra != where:
        line += f" Closest address: {extra.split(',')[0]}."
    return prefix + line


def _weather_reply(facts: dict) -> str:
    w = facts.get("weather") or {}
    loc = (facts.get("place") or {}).get("city") or "your area"
    temp = w.get("temperature_c")
    cond = w.get("condition") or ("rain" if w.get("rainy") else "unknown")
    if temp is None:
        return f"I could not fetch live weather for {loc}."
    rain = " It is raining — better stay indoor for the first hour." if w.get("rainy") else ""
    return f"Live weather in {loc}: {temp}°C, {cond}.{rain}"


def _memory_reply(facts: dict) -> str:
    mems = facts.get("memories") or []
    if not mems:
        return "I don't have lasting preferences stored for you yet."
    return "What I know about you: " + "; ".join(mems[:5]) + "."


def _help_reply() -> str:
    return (
        "Ask a short question (location, weather, what I remember), "
        "or describe an evening you want — mood, budget, time — and I'll build a plan."
    )


def answer_chat(message: str, user_id: str, lat: float | None, lon: float | None,
                location_names: dict | None = None) -> dict[str, Any]:
    topic = classify_turn(message)["topic"]
    facts = live_facts(user_id, lat, lon, location_names)
    if topic == "location":
        reply = _location_reply(facts)
    elif topic == "weather":
        reply = _weather_reply(facts)
    elif topic == "memory":
        reply = _memory_reply(facts)
    elif topic == "help":
        reply = _help_reply()
    else:
        llm = router.extract_json(
            CHAT_PROMPT.format(
                facts={
                    "location": facts.get("place"),
                    "weather": facts.get("weather"),
                    "mem0": facts.get("memories"),
                    "gps_live": not facts.get("used_default_location"),
                },
                message=message,
            )
        )
        reply = (llm.get("reply") or "").strip() or _help_reply()
    return {
        "mode": "chat",
        "topic": topic,
        "reply": reply,
        "location": facts.get("place"),
        "weather": facts.get("weather"),
        "used_default_location": facts.get("used_default_location"),
        "plan": None,
    }
