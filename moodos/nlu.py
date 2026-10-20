from __future__ import annotations

import logging
import math
import re
import threading
from typing import Any

from moodos.config import settings
from moodos.llm import router

log = logging.getLogger("moodos.nlu")

# Extraction is the FIRST LLM call in /api/plan (orchestrator.run_pipeline),
# so an unbudgeted extract blocks everything behind it -- worst case Groq
# 25s + 7 Gemini models x 25s ~= 200s. Same pattern as
# orchestrator._plan_with_budget: daemon thread + join, then fall back to the
# instant heuristic slots, which are already a complete answer. The thread is
# abandoned on overrun but every LLM leg is itself bounded by
# llm.LLM_TIMEOUT_S (25s), so it cannot linger past that.
EXTRACT_BUDGET_S = 8.0


PLAN_HINTS = (
    "recommend",
    "suggest",
    "plan",
    "outing",
    "evening",
    "exhausted",
    "what should i do",
    "go out",
    "movie night",
    "date night",
    "weekend",
)
HOME_HINTS = (
    "stay home", "stay in", "at home", "watch at home", "movie at home",
    "don't want to go", "dont want to go", "don't wanna go",
    "no theater", "no theatre", "no cinema", "skip cinema", "skip theater",
    "netflix", "streaming", "watch something", "couch", "binge",
    "not going out", "indoor movie", "home movie", "ott",
    "don't feel like going out", "dont feel like going out",
    "watch a film", "watch a movie", "lazy",
)
LOCATION_HINTS = (
    "where am i",
    "current location",
    "curr location",
    "my location",
    "my loc",
    "what is my location",
    "what's my location",
    "gps",
)
WEATHER_HINTS = ("weather", "temperature", "raining", "rain now", "how's the weather", "how is the weather")
MEMORY_HINTS = ("what do you know about me", "my preference", "remember me", "what i like")
HELP_HINTS = ("what can you do", "help", "how do you work", "who are you")

# --- Music language ---------------------------------------------------------
# Map every way a user might name a music language to one canonical label, so
# searches like "calm Hindi playlist" / "upbeat Gujarati songs" always resolve.
MUSIC_LANGUAGE_TERMS = {
    "hindi": "hindi", "bollywood": "hindi", "hindustani": "hindi", "desi": "hindi",
    "gujarati": "gujarati", "gujrati": "gujarati",
    "punjabi": "punjabi", "panjabi": "punjabi",
    "tamil": "tamil", "tamizh": "tamil", "tamal": "tamil",
    "telugu": "telugu",
    "kannada": "kannada", "kanada": "kannada", "kanarese": "kannada",
    "marathi": "marathi",
    "bengali": "bengali", "bangla": "bengali",
    "malayalam": "malayalam", "mallu": "malayalam",
    "bhojpuri": "bhojpuri",
    "odia": "odia", "oriya": "odia",
    "assamese": "assamese",
    "urdu": "urdu",
    "tulu": "tulu",
    "konkani": "konkani",
    "english": "english",
}
MUSIC_TERMS = (
    "song", "songs", "music", "playlist", "listen", "album", "gaana",
    "track", "tune", "melody", "singer", "artist", "band", "singing",
    "soundtrack", "bhajan", "ghazal", "qawwali", "aarti",
)

# Regional language the user most likely enjoys, given where they are. Used as a
# fallback when they never said what language they listen to: music suggestions
# should feel local, not a generic English cross-continent mix.
STATE_LANGUAGE = {
    "gujarat": "gujarati", "daman and diu": "gujarati", "dadra and nagar haveli": "gujarati",
    "maharashtra": "marathi",
    "goa": "konkani",
    "punjab": "punjabi",
    "tamil nadu": "tamil", "puducherry": "tamil",
    "kerala": "malayalam",
    "karnataka": "kannada",
    "telangana": "telugu", "andhra pradesh": "telugu",
    "west bengal": "bengali",
    "bihar": "bhojpuri",
    "assam": "assamese",
    "odisha": "odia",
    "uttar pradesh": "hindi", "delhi": "hindi", "haryana": "hindi",
    "rajasthan": "hindi", "madhya pradesh": "hindi", "jharkhand": "hindi",
    "chhattisgarh": "hindi", "uttarakhand": "hindi", "himachal pradesh": "hindi",
    "jammu and kashmir": "kashmiri", "manipur": "manipuri", "mizoram": "mizo",
    "meghalaya": "khasi", "sikkim": "nepali",
}
CITY_LANGUAGE = {
    "ahmedabad": "gujarati", "surat": "gujarati", "vadodara": "gujarati",
    "rajkot": "gujarati", "gandhinagar": "gujarati", "bhavnagar": "gujarati",
    "mumbai": "marathi", "pune": "marathi", "nagpur": "marathi", "thane": "marathi",
    "nashik": "marathi", "aurangabad": "marathi", "kolhapur": "marathi",
    "amritsar": "punjabi", "ludhiana": "punjabi", "jalandhar": "punjabi",
    "chennai": "tamil", "madurai": "tamil", "coimbatore": "tamil",
    "hyderabad": "telugu", "warangal": "telugu", "vijayawada": "telugu",
    "visakhapatnam": "telugu", "guntur": "telugu", "tirupati": "telugu",
    "bengaluru": "kannada", "bangalore": "kannada", "mysore": "kannada", "hubli": "kannada",
    "kochi": "malayalam", "kozhikode": "malayalam", "thiruvananthapuram": "malayalam",
    "kolkata": "bengali", "howrah": "bengali",
    "jaipur": "hindi", "delhi": "hindi", "lucknow": "hindi", "kanpur": "hindi",
    "agra": "hindi", "varanasi": "hindi", "indore": "hindi", "bhopal": "hindi",
    "patna": "bhojpuri", "guwahati": "assamese", "bhubaneswar": "odia",
}


def detect_music_language(message: str) -> str | None:
    """Language the user asked to listen to music in (explicit request), or None.

    Requires a music-ish context word so "I like Hindi films" doesn't hijack the
    playlist, but "want to listen to Punjabi songs" does.
    """
    text = message.lower()
    if not any(w in text for w in MUSIC_TERMS):
        return None
    for term, canonical in MUSIC_LANGUAGE_TERMS.items():
        if term in text:
            return canonical
    return None


def infer_locale_language(city: str | None, state: str | None) -> str | None:
    """Regional language for where the user is right now (fallback when they
    didn't name a language). Matches the state first, then the city."""
    if state:
        s = state.lower().strip()
        for key, lang in STATE_LANGUAGE.items():
            if key in s:
                return lang
    if city:
        c = city.lower().strip()
        for key, lang in CITY_LANGUAGE.items():
            if key in c:
                return lang
    return None


def classify_turn(message: str) -> dict[str, str]:
    text = message.lower().strip()
    if any(h in text for h in HOME_HINTS):
        return {"mode": "plan", "topic": "experience", "stay_home": True}
    if any(h in text for h in PLAN_HINTS) or ("₹" in message) or re.search(r"\b\d+\s*(hours|hrs|hour)\b", text):
        return {"mode": "plan", "topic": "experience"}
    if any(h in text for h in LOCATION_HINTS) or (text.startswith("where") and "i" in text):
        return {"mode": "chat", "topic": "location"}
    if any(h in text for h in WEATHER_HINTS):
        return {"mode": "chat", "topic": "weather"}
    if any(h in text for h in MEMORY_HINTS):
        return {"mode": "chat", "topic": "memory"}
    if text in {"hi", "hello", "hey", "thanks", "thank you"} or any(h in text for h in HELP_HINTS):
        return {"mode": "chat", "topic": "help"}
    if text.endswith("?") and not any(h in text for h in PLAN_HINTS):
        return {"mode": "chat", "topic": "other"}
    return {"mode": "plan", "topic": "experience"}


EXTRACT_PROMPT = """Extract MoodOS slots from the user message.
Return JSON keys:
intent, current_mood, desired_mood, mood_intensity (low|medium|high),
mood_trajectory (array of short steps),
budget_inr (number or null), duration_hours (number or null),
party_size (number or null — how many people the outing/budget covers,
  e.g. "Rs5000 for 5 friends" -> 5; 1 or null for a solo outing),
social (solo|friends|family|date|unknown), intensity (low|medium|high),
city (string or null), implicit_preferences (array of strings),
constraints (array of strings),
stay_home (boolean, true if user wants to stay home/watch at home/no theater),
food_priority (boolean, true when the user emphasizes the meal/food as the main
  thing — e.g. "food is the main thing", "a really good meal", "best dinner",
  "treat me to something nice to eat", "I'm craving x"; false for a passing
  mention like "a quiet dinner and a movie"),
want_movie (boolean, true when the user explicitly asks to watch a movie this
  outing — e.g. "I really want to watch a movie", "suggest a film to watch",
  "let's do a cinema night", "watch a movie tonight"; false when a film is only
  mentioned in passing or not at all),
music_language (string or null, the spoken language the user wants music/songs
  in — e.g. "gujarati", "hindi", "hindi" for Bollywood, "punjabi", "tamil",
  "telugu", "marathi", "bengali", "english"; null when they didn't mention a
  language for music).

User message:
{message}
"""


def heuristic_extract(message: str) -> dict[str, Any]:
    text = message.lower()
    budget = None
    m = re.search(r"(?:₹|\binr\b|\brs\.?)\s*([0-9]{2,7}(?:,[0-9]{3})*)", text, re.I)
    if m:
        budget = int(m.group(1).replace(",", ""))
    else:
        m = re.search(r"\b([0-9]{3,7})\s*(?:rupees|rs)\b", text)
        if m:
            budget = int(m.group(1))

    hours = None
    hm = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours|hour|hrs|hr)\b", text)
    if hm:
        hours = float(hm.group(1))
    if "four hours" in text or "4 hours" in text:
        hours = 4.0

    # Headcount for group outings: "Rs5000 for 5 friends", "5 of us",
    # "a group of 6". budget_inr stays the GROUP total; consumers scale
    # per-person cost estimates by party_size (see ranking.hard_filter).
    party_size = None
    pm = re.search(r"\b(\d{1,2})\s*(?:friends?|people|ppl|persons?|of us)\b", text)
    if not pm:
        pm = re.search(r"\b(?:family|group|party)\s+of\s+(\d{1,2})\b", text)
    if pm:
        n = int(pm.group(1))
        if 1 < n <= 50:
            party_size = n

    social = "solo" if any(w in text for w in ("alone", "solo", "by myself")) else "unknown"
    intensity = "low" if any(w in text for w in ("nothing intense", "exhausted", "tired", "low energy", "calm")) else "medium"
    current = "exhausted" if "exhaust" in text or "tired" in text else "neutral"
    desired = "relaxed" if intensity == "low" else "entertained"
    rainy_want = "rain" in text
    stay_home = any(h in text for h in HOME_HINTS)
    food_words = ("dinner", "lunch", "meal", "food", "eat", "eats", "restaurant", "dining", "treat me to")
    emphasis = (
        "main thing", "main event", "really good", "the best", "best dinner", "best meal",
        "must", "treat", "craving", "hungry", "priority", "special", "nice dinner",
        "good meal", "proper meal", "proper sit", "sit down", "great meal", "go all out",
        "worth it", "something nice",
    )
    food_priority = any(f in text for f in food_words) and any(e in text for e in emphasis)
    want_movie = any(
        w in text
        for w in (
            "watch a movie", "watch a film", "see a movie", "see a film",
            "movie tonight", "movie night", "go to the movies", "catch a movie",
            "catch a film", "cinema", "theatre", "theater", "film to watch",
        )
    ) or " movie" in f" {text}" or " film" in f" {text}"

    return {
        "intent": "relaxation / solo outing" if social == "solo" and intensity == "low" else "personalized outing",
        "current_mood": current,
        "desired_mood": desired,
        "mood_intensity": intensity,
        "mood_trajectory": [current, "calm", "light entertainment", desired],
        "budget_inr": budget,
        "duration_hours": hours,
        "party_size": party_size,
        "social": social,
        "intensity": intensity,
        "city": settings.default_city,
        "implicit_preferences": ["nearby", "comfortable", "low-effort"] if intensity == "low" else [],
        "constraints": (["no high intensity"] if intensity == "low" else []) + (["rain"] if rainy_want else []) + (["stay_home"] if stay_home else []),
        "stay_home": stay_home,
        "food_priority": food_priority,
        "want_movie": want_movie,
        "music_language": detect_music_language(message),
        "_agent": "heuristic",
        "_model": "rules",
    }


def extract_intent(message: str) -> dict[str, Any]:
    base = heuristic_extract(message)
    holder: dict[str, Any] = {}
    failed: list[str] = []

    def _run() -> None:
        # A crashing LLM leg must not escape the thread: heuristic slots are
        # a complete answer, so record why we got nothing and fall through.
        try:
            data = router.extract_json(EXTRACT_PROMPT.format(message=message))
        except Exception as exc:  # noqa: BLE001 - any provider failure
            failed.append(str(exc) or type(exc).__name__)
            return
        if data:
            holder.update(data)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(EXTRACT_BUDGET_S)
    llm = dict(holder)
    if not llm:
        # "budget exceeded" is reserved for a REAL timeout: the thread is
        # still running. Finished-with-nothing and raised are logged apart,
        # so an instant empty answer can never look like an overrun.
        if thread.is_alive():
            log.warning(
                "intent extraction budget exceeded (%.1fs); using heuristic slots",
                EXTRACT_BUDGET_S,
            )
        elif failed:
            log.warning(
                "intent extraction raised; using heuristic slots: %s", failed[0]
            )
        else:
            log.warning("LLM returned nothing; using heuristic slots")
        return base
    _heuristic_numeric = {"duration_hours", "budget_inr", "party_size"}
    merged = {**base, **{k: v for k, v in llm.items() if v not in (None, "", [])}}
    for k in _heuristic_numeric:
        if base.get(k) is not None:
            merged[k] = base[k]
    merged["_agent"] = llm.get("_agent", base["_agent"])
    merged["_model"] = llm.get("_model", base["_model"])
    return merged


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
