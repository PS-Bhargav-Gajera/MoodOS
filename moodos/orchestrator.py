from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any

from moodos import actions, providers
from moodos import journal
from moodos.config import settings
from moodos.db import ensure_user, save_event
from moodos.llm import router
from moodos.location_service import location_service
from moodos.mcp_server import mcp
from moodos.memory import mem0
import moodos.nlu as nlu
from moodos.nlu import extract_intent, haversine_km
from moodos.rag import knowledge
from moodos.ranking import hard_filter, party_size, rerank, score_item

log = logging.getLogger("moodos.orchestrator")

# Lightweight "seen recently" guard so we don't re-suggest the exact same
# movie / playlist on every single request without relying on fixed templates.
_seen_recent: dict[str, list[str]] = {}

# --- music query rotation -------------------------------------------------
# A single fixed query per mood means the same Spotify results every time. We
# instead pick from a pool of stylistic seeds, biased by time of day, weather and
# whether the user wants energy or calm, and prefer whichever seed we have used
# least recently (tracked in the shown_items log).
_CALM_SEEDS = ("lofi", "acoustic", "ambient", "instrumental", "indie mellow", "soft piano")
_ENERGY_SEEDS = ("upbeat", "dance pop", "funk", "rock", "party hits", "electronic")
_DAYPART_SEEDS = {
    "morning": ("acoustic", "indie mellow", "folk", "soft piano", "upbeat"),
    "afternoon": ("indie mellow", "funk", "acoustic", "lofi", "jazz"),
    "evening": ("lofi", "ambient", "soft piano", "jazz", "instrumental"),
    "night": ("ambient", "electronic", "instrumental", "late night", "deep house"),
}


def _time_bucket(now: datetime | None = None) -> str:
    h = (now or datetime.now()).hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return "night"


def _music_seed_candidates(slots: dict, weather: dict | None) -> list[str]:
    """Ordered stylistic seeds for this mood/time/weather, most fitting first."""
    weather = weather or {}
    text = str(slots.get("music_language") or "")
    intensity = str(slots.get("intensity") or "low").lower()
    current = str(slots.get("current_mood") or "").lower()
    wants_energy = intensity == "high" or any(
        w in current for w in ("happy", "excited", "energiz", "bored", "restless")
    )
    pool = _ENERGY_SEEDS if wants_energy else _CALM_SEEDS

    ordered: list[str] = []
    for seed in _DAYPART_SEEDS.get(_time_bucket(), _CALM_SEEDS):
        if seed not in ordered:
            ordered.append(seed)
    for seed in pool:
        if seed not in ordered:
            ordered.append(seed)

    cond = str(weather.get("condition") or weather.get("weather_condition") or "").lower()
    if any(w in cond for w in ("rain", "storm", "drizzle", "snow")):
        for seed in ("lofi", "ambient", "piano"):
            if seed in ordered:
                ordered.remove(seed)
            ordered.insert(0, seed)
    return ordered


def _rotate_music_query(base: str, slots: dict, weather: dict | None,
                        user_id: str = "demo") -> str:
    """Attach the least-recently-used stylistic seed to the base query.

    The seed is recorded so the next request prefers a different one, which is
    what stops Spotify returning an identical playlist every evening.
    """
    from moodos import db as _db

    candidates = _music_seed_candidates(slots, weather)
    if not candidates:
        return base
    try:
        used = [t.lower() for t in _db.recent_shown(user_id, "music_seed", limit=len(candidates) * 2)]
    except Exception:
        used = []
    chosen = next((c for c in candidates if c not in used), candidates[0])
    try:
        _db.record_shown(user_id, "music_seed", chosen)
    except Exception:
        pass
    return f"{base} {chosen}".strip()


def _exclude_recent_tracks(tracks: list[dict] | None, user_id: str) -> list[dict]:
    """Drop tracks we already put in front of this user.

    Only removes genuinely repeated tracks; if the filter would empty the pool
    we keep the original results rather than showing an empty music step.
    """
    from moodos import db as _db

    try:
        recent = {t.lower() for t in _db.recent_shown(user_id, "track", limit=40)}
    except Exception:
        return list(tracks or [])
    if not recent:
        return list(tracks or [])
    kept = [t for t in (tracks or []) if (t.get("title") or "").lower() not in recent]
    return kept or list(tracks or [])


def _excluded_movie_titles(user_id: str) -> set[str]:
    """Normalised titles of movies already suggested, used to filter the pool."""
    from moodos import db as _db

    try:
        return {_norm_title(t) for t in _db.recent_shown(user_id, "movie", limit=25) if t}
    except Exception:
        return set()


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _derive_search_query(message: str, slots: dict, kind: str,
                         preferences: dict | None = None) -> str:
    """Build a natural, message-driven search query for a media kind.

    Uses the user's own words (movie/music hints) plus their stated mood/intent
    and any stored preferences (movie language/genre from happy reactions), so
    future queries naturally lean toward what they liked.
    """
    preferences = preferences or {}
    text = message.lower()
    mood_words = []
    desired = (slots.get("desired_mood") or "").lower()
    if desired:
        mood_words.append(desired)
    if any(w in text for w in ("exhausted", "tired", "relax", "calm", "quiet", "low", "stress")):
        mood_words.append("calm")
    if any(w in text for w in ("happy", "celebrat", "energiz", "fun", "excit", "party", "high")):
        mood_words.append("upbeat")
    if "romance" in text or "date" in text:
        mood_words.append("romantic")
    if "comedy" in text or "funny" in text or "laugh" in text:
        mood_words.append("comedy")

    genre = ""
    for g in (
        "action", "adventure", "comedy", "drama", "romance", "romantic",
        "thriller", "horror", "animation", "mystery", "fantasy", "sci-fi",
        "musical", "documentary",
    ):
        if g in text:
            genre = g
            break

    if kind == "movie":
        # User-specified genre wins; fall back to learned preference, then default.
        base = genre or (preferences.get("movie_genres") or [None])[0] or "heartwarming"
        lang = preferences.get("movie_language")
        if lang:
            base = f"{lang} {base}"
        if mood_words:
            return f"{base} {mood_words[0]} film"
        return f"{base} movie"
    else:
        vibe = mood_words[0] if mood_words else "chill"
        lang = (slots.get("music_language") or "").strip()
        if lang and lang != "english":
            if genre:
                return f"{genre} {vibe} {lang} playlist"
            return f"{vibe} {lang} playlist"
        if genre:
            return f"{genre} {vibe} playlist"
        return f"{vibe} playlist"


# --- preference signals (readable names -> TMDB codes) ----------------------

_LANGUAGE_CODES = {
    "hindi": "hi", "english": "en", "tamil": "ta", "telugu": "te",
    "kannada": "kn", "malayalam": "ml", "marathi": "mr", "bengali": "bn",
    "punjabi": "pa", "gujarati": "gu", "bhojpuri": "bho", "odia": "or",
    "assamese": "as", "urdu": "ur",
}

_MOVIE_LANG_RE = re.compile(r"prefers ([a-z]+)-language movies", re.I)
_MOVIE_GENRE_RE = re.compile(r"enjoys ([a-z][a-z\- ]+?) movies", re.I)
_MUSIC_LANG_RE  = re.compile(r"enjoys ([a-z][a-z\- ]+?) music", re.I)
_CUISINE_RE     = re.compile(r"enjoys ([a-z][a-z\- ]+?) food", re.I)


def _preference_signals(memories: list[dict]) -> dict:
    """Flatten stored preference memories into a small dict of structured
    signals used to bias search queries and scoring (all else equal — mood /
    budget / distance still govern).

    Only memories with explicit, clear phrasing feed back as structured
    signals; ambiguous text is safely ignored.
    """
    signals: dict[str, Any] = {
        "movie_language": None,      # readable name e.g. "hindi"
        "movie_language_code": None, # TMDB code e.g. "hi"
        "movie_genres": [],
        "music_language": None,
        "cuisine": None,
    }
    for mem in memories or []:
        text = str(mem.get("text") or "").strip()
        if not text:
            continue
        m = _MOVIE_LANG_RE.search(text)
        if m:
            name = m.group(1).strip().lower()
            signals["movie_language"] = name
            signals["movie_language_code"] = _LANGUAGE_CODES.get(name)
        m = _MOVIE_GENRE_RE.search(text)
        if m:
            g = m.group(1).strip().lower()
            if g and g not in signals["movie_genres"]:
                signals["movie_genres"].append(g)
        m = _MUSIC_LANG_RE.search(text)
        if m:
            signals["music_language"] = m.group(1).strip().lower()
        m = _CUISINE_RE.search(text)
        if m:
            signals["cuisine"] = m.group(1).strip().lower()
    return signals


# ---------------------------------------------------------------------------

def _movie_candidates(cinemas: list[dict], lat: float, lon: float,
                      region: str = "IN", films: list[dict] | None = None) -> list[dict]:
    """Turn real map-found cinemas into movie candidates using live TMDB titles.

    Runtime/genres come from TMDB when a key is available. Real per-cinema
    showtimes are not available for India through a free API, so the shown time
    is always an estimate ("check the cinema for exact timing").
    """
    if not cinemas:
        return []
    region = (region or "IN").upper()
    films = films if films is not None else providers.tmdb_now_playing(region=region, limit=max(8, len(cinemas)))
    if not films:
        films = providers.tmdb_trending("movie", "week", limit=8)
    if not films:
        return []
    shows = actions.list_showtimes(lat=lat, lon=lon, limit=len(films), region=region, movies=films)
    out: list[dict] = []
    for i, venue in enumerate(cinemas):
        show = shows[i % len(shows)] if shows else None
        if not show:
            continue
        venue_name = venue.get("name") or venue.get("title") or "Nearby cinema"
        tmdb_id = show.get("tmdb_id")
        detail = providers.tmdb_movie_details(tmdb_id) if tmdb_id else {}
        duration_min = detail.get("runtime_min")
        is_estimate = not duration_min
        genres = detail.get("genres") or []
        genre_known = bool(genres)
        overview = detail.get("overview") or show.get("overview") or ""
        tagline = detail.get("tagline") or ""
        fit, fit_reason = (
            providers.classify_movie_fit(genres, overview, tagline)
            if genre_known else ("unknown", "genre metadata unavailable")
        )
        out.append(
            {
                "id": f"movie:{venue.get('id', i)}",
                "title": show["movie"],
                "kind": "movie",
                "venue": venue_name,
                "text": f"Showing at {venue_name} · {show['time']} (est.)",
                "estimated_cost": show["price_inr"],
                "duration_min": duration_min if duration_min else 130,
                "runtime_min_real": duration_min,
                "runtime_source": "tmdb" if duration_min else "estimate",
                "is_estimate": bool(is_estimate),
                "intensity": "low",
                "source": "overpass-cinema+" + (show.get("provider") or "tmdb"),
                "show": {**show, "showtime_estimated": True, "venue": venue_name, "cinema": venue_name},
                "showtime_estimated": True,
                "showtime_disclaimer": (
                    f"Showtime is an estimate — check {venue_name} for exact timing."
                ),
                "criteria": {"title": show["movie"], "description": overview[:120]},
                "genres": genres,
                "genre_source": "tmdb" if genre_known else "unknown",
                "genre_fit": fit,
                "genre_fit_reason": fit_reason,
                "mood_fit_verified": bool(genre_known),
                "runtime_note": f"Runtime from TMDB ({duration_min} min)" if not is_estimate else "Runtime/showtime is an estimate",
                "tmdb_id": tmdb_id,
                "poster_url": show.get("poster_url") or detail.get("poster_url"),
                "review_quality": float(detail.get("vote_average") or 7.0),
                "moods": ["calm", "warm"],
                "lat": float(venue.get("lat") or lat),
                "lon": float(venue.get("lon") or lon),
                "has_venue": True,
            }
        )
    return out


def _fmt_km(km: float | None) -> str | None:
    if km is None:
        return None
    if km < 1:
        return f"{int(km * 1000)} m from you"
    return f"{km:.1f} km from you"


def _walk_min(km: float | None) -> int | None:
    if km is None:
        return None
    return max(4, int(round(km * 12)))


def _distance(item: dict, lat: float, lon: float) -> float | None:
    if "lat" in item and "lon" in item:
        try:
            return round(haversine_km(lat, lon, float(item["lat"]), float(item["lon"])), 2)
        except (TypeError, ValueError):
            return None
    return None


def _recently_suggested_titles() -> list[str]:
    return [t for k, v in _seen_recent.items() if k.startswith("suggested:") for t in v]


def _apply_repeat_penalty(item: dict, score: float, music_q: str) -> float:
    """Suppress items we've already suggested recently so plans keep varying."""
    title = (item.get("title") or "").lower()
    recent = [t.lower() for t in _recently_suggested_titles()]
    if not recent or not title:
        return score
    if any(r in title or title in r for r in recent):
        return score - 0.35
    return score


def _remember_suggestions(plan: dict) -> None:
    for step in plan.get("steps") or []:
        title = (step.get("title") or "").strip()
        if not title:
            continue
        key = "suggested:" + step.get("kind", "item")
        _seen_recent.setdefault(key, []).append(title)
        _seen_recent[key] = _seen_recent[key][-12:]


def _record_shown_items(plan: dict, user_id: str) -> None:
    """Persist what we actually put in front of the user.

    Durable (SQLite) rather than the in-process _seen_recent dict, so repeats
    are still suppressed after a server restart. Kept out of Mem0 on purpose:
    "we already showed this" is bookkeeping, not a preference, and writing it
    as an assistant message would pollute the semantic memory.
    """
    from moodos import db as _db

    try:
        for step in plan.get("steps") or []:
            kind = str(step.get("kind") or "").lower()
            title = (step.get("title") or "").strip()
            if kind in {"movie", "streaming"} and title:
                _db.record_shown(user_id, "movie", title)
            elif kind == "music":
                for t in step.get("tracks") or []:
                    name = (t.get("title") or "").strip()
                    if name:
                        _db.record_shown(user_id, "track", name)
    except Exception as exc:  # never let bookkeeping break a plan
        log.warning("could not record shown items: %s", exc)


def _attach_geo(step: dict, ranked: list[dict]) -> dict:
    title = (step.get("title") or "").lower()
    for item in ranked:
        it = (item.get("title") or "").lower()
        if it and (it in title or title in it):
            step["distance_km"] = item.get("distance_km")
            step["distance_label"] = _fmt_km(item.get("distance_km"))
            step["walk_min"] = item.get("walk_min") or _walk_min(item.get("distance_km"))
            step["drive_min"] = item.get("drive_min")
            step["routing_source"] = item.get("routing_source")
            step["category"] = item.get("category")
            step["address"] = item.get("address")
            step["phone"] = item.get("phone")
            step["website"] = item.get("website")
            if step.get("_lat") is None and item.get("lat") is not None:
                step["_lat"] = item.get("lat")
                step["_lon"] = item.get("lon")
            return step
    if step.get("distance_km") is not None:
        step["distance_label"] = _fmt_km(step.get("distance_km"))
        step["walk_min"] = step.get("walk_min") or _walk_min(step.get("distance_km"))
    return step

PLAN_PROMPT = """You are MoodOS Experience Planner (Gemini-first).
Build ONE coherent sequence, not a dump of isolated items.
Return JSON:
{{
  "steps": [{{"order":1,"kind":"walk|cafe|food|restaurant|movie|streaming|music","title":"","duration_min":0,"cost_inr":0,"why":""}}],
  "total_cost_inr": 0,
  "total_duration_min": 0,
  "explanation": "one short paragraph grounded in the provided facts",
  "uncertainty": []
}}
Rules:
- Stay within budget_inr and duration_hours * 60 minutes total.
- NEVER invent a generic walk or a place that is not in ranked candidates.
  A walk step is allowed only when a real park/garden title is in the list.
- NEVER create travel steps. Travel legs are added automatically.
- Use ONLY place titles from the ranked candidates list verbatim.
  Never invent place names.
- You MUST spend at least 60% of budget_inr across the steps.
  With ₹1200 budget, total cost_inr across steps must be >= ₹720.
- budget_inr is the TOTAL for the whole group. Candidate estimated_cost is
  per-person: every cost_inr you write must be the group total
  (per-person price x party_size). "Rs5000 for 5 friends" means the steps
  together may spend up to ₹5000, each step's cost being 5x the ticket price.
  Include a movie step (cost ~₹220 x party_size) if duration_hours >= 3
  and stay_home is false.
- Prefer quiet/low intensity if intensity is low.
- If stay_home is true, use kind=streaming not movie.
- Maximum 5 steps total. No filler steps.
User slots: {slots}
Mem0: {memory}
Weather: {weather}
Ranked candidates: {candidates}
Live cinema pairings (TMDB now-playing + OSM venues; showtimes estimated): {shows}
"""


_CATEGORY_LABEL = {"preference": "Pref", "episodic": "Past", "pattern": "Pattern", "feedback": "Feedback"}


def _memory_block(memories: list[dict], max_items: int = 5, max_len: int = 140) -> str:
    """Label and truncate memories so they inform the planner without crowding
    the prompt (a wall of raw text would dilute the duration/budget rules)."""
    if not memories:
        return "None on file."
    lines: list[str] = []
    for m in memories[:max_items]:
        label = _CATEGORY_LABEL.get(m.get("category"), "Mem")
        text = str(m.get("text") or "").strip()
        if not text:
            continue
        if len(text) > max_len:
            text = text[: max_len - 1].rstrip() + "…"
        lines.append(f"[{label}] {text}")
    return "\n".join(lines) or "None on file."


def _plan_with_budget(prompt: str, ranked: list, slots: dict, weather: dict) -> dict[str, Any]:
    """Run the LLM planner with a hard time budget.

    If the LLM is slow (slow network, rate limit, etc.) we fall back to the
    instant heuristic plan so the request always returns promptly instead of
    hanging the UI.
    """
    result: dict[str, Any] = {}
    import threading

    def _run() -> None:
        d = router.plan_json(prompt)
        if d:
            result.update(d)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=35.0)
    if result.get("steps"):
        return result
    log.warning("LLM plan exceeded budget; using heuristic plan")
    return {}


def handle_message(
    message: str,
    user_id: str = "demo",
    lat: float | None = None,
    lon: float | None = None,
    prompt_name: str | None = None,
    location_names: dict | None = None,
) -> dict[str, Any]:
    from moodos.chat import answer_chat
    from moodos.crisis import crisis_reply, is_crisis
    from moodos.nlu import classify_turn

    # Same shared guard as the /api/plan route (defense-in-depth for direct
    # callers): crisis never reaches the chat LLM leg or run_pipeline.
    if is_crisis(message):
        return crisis_reply()
    turn = classify_turn(message)
    if turn["mode"] == "chat":
        return answer_chat(message, user_id, lat, lon, location_names)
    bundle = run_pipeline(message, user_id, lat, lon, prompt_name, location_names)
    bundle["mode"] = "plan"
    return bundle


_RELAX_TARGET_MOODS = {"relaxed", "calm", "calmer", "peaceful", "refreshed", "happy", "de-stressed", "unwind"}


def _wants_relax_target(slots: dict) -> bool:
    """True when the plan should lean calm/light — applies strict genre filtering."""
    traj = [str(m).lower() for m in (slots.get("mood_trajectory") or [])]
    desired = str(slots.get("desired_mood") or "").lower()
    current = str(slots.get("current_mood") or "").lower()
    intensity = str(slots.get("intensity") or "low").lower()
    if intensity == "low":
        return True
    if desired in _RELAX_TARGET_MOODS:
        return True
    if any(m in _RELAX_TARGET_MOODS for m in traj):
        return True
    if current and any(w in current for w in ("stress", "exhaust", "tired", "anxious", "tense")):
        return True
    return False


def _pick_best_movie(movies: list[dict], slots: dict) -> dict | None:
    """Choose the movie candidate that best matches the target mood, using real
    TMDB genre metadata when available.

    For a tone-sensitive (calm/relax) target, films whose genre/tone can't be
    verified (genre_fit == 'unknown') and films verified as intense ('poor') are
    EXCLUDED from selection — an unverified film could easily be tonally wrong,
    so we never present an unverified film as a confirmed mood fit. Exception:
    when the user EXPLICITLY asked to watch a movie (want_movie), we never
    silently drop their request — we fall back to the best-available candidate
    with an honest 'couldn't fully verify tone' disclaimer instead. Only when
    there are no movie candidates at all do we return None."""
    if not movies:
        return None
    relax = _wants_relax_target(slots)
    want_movie = bool(slots.get("want_movie"))
    if relax:
        eligible = [
            m for m in movies
            if bool(m.get("mood_fit_verified"))
            and str(m.get("genre_fit") or "unknown") in {"good", "neutral"}
        ]
        if not eligible:
            if want_movie:
                # Explicit request: surface the closest match, honestly flagged.
                return sorted(movies, key=lambda m: -float(m.get("final_score") or 0))[0]
            return None
        order = {"good": 0, "neutral": 1}
    else:
        eligible = list(movies)
        order = {"good": 0, "neutral": 0, "unknown": 0, "poor": 1}
    return sorted(
        eligible,
        key=lambda m: (
            order.get(str(m.get("genre_fit") or "unknown"), 1),
            -float(m.get("final_score") or 0),
        ),
    )[0]


def _venue_clause(venue) -> str:
    """Return a display-safe venue clause, or '' when the venue is unknown.
    Guards against 'at None' leaking into user-facing text."""
    if not venue:
        return ""
    return f" at {venue}"


def _movie_blurb(movie: dict | None, slots: dict) -> str:
    """Write a movie 'why' that is VERIFIED against real TMDB genre metadata.

    We never invent a mood-fit justification for a film we haven't verified:
    if the genre/tone isn't confirmed, we say so instead of claiming it's light
    entertainment. For a relax target, an intense film is flagged rather than
    praised. The venue clause is omitted whenever the cinema name is missing.
    """
    if not movie:
        return ""
    title = movie.get("title") or ""
    venue = movie.get("venue")
    vclause = _venue_clause(venue)
    genres = movie.get("genres") or []
    fit = str(movie.get("genre_fit") or "unknown")
    verified = bool(movie.get("mood_fit_verified"))
    genre_names = ", ".join(genres) if genres else "unavailable"

    if not verified:
        base = (
            f"\"{title}\" is showing now{vclause}, but I couldn't verify its genre or "
            f"tone from a listing — treat the run time/show as an estimate"
        )
        if venue:
            base += f" and check {venue} for current listings"
        base += " before relying on it as a mood fit."
        return base

    if not _wants_relax_target(slots):
        # Not a calm target — a neutral/poor fit isn't actively harmful; just report facts.
        base = f"\"{title}\" ({genre_names}){vclause}."
        if fit == "poor":
            base += " Note: it's on the more intense side, so it may not be an unwind pick."
        return base

    if fit == "good":
        return (
            f"\"{title}\" ({genre_names}){vclause} — a genuinely light, mood-appropriate "
            f"pick for a calm/relaxed evening (genre verified from TMDB)."
        )
    if fit == "neutral":
        return (
            f"\"{title}\" ({genre_names}){vclause}. Its tone is neutral (not clearly "
            f"light or intense) — fine to watch, but manage expectations if you want pure de-stress."
        )
    # poor fit on a relax target — this shouldn't normally be chosen, but be honest.
    reason = movie.get("genre_fit_reason")
    reason_clause = f" ({reason})" if reason else ""
    return (
        f"\"{title}\"{vclause} — heads up: this one reads intense/psychologically "
        f"heavy, which isn't ideal for a calm/de-stress evening{reason_clause}. "
        f"Prefer a light comedy or feel-good film instead if you want to fully unwind."
    )


def _pick_dining(ranked: list[dict], slots: dict) -> tuple[dict | None, dict | None]:
    """Choose the restaurant and cafe stops from ranked candidates.

    When the user explicitly makes food the main thing and there is budget
    headroom (>= 800), prefer a substantial sit-down restaurant over the
    generic top-ranked candidate — so a quick ₹150 dairy-parlour snack doesn't
    win just because it ranks first. Otherwise keep the original first-match
    behaviour."""
    restaurants = [c for c in ranked if c.get("kind") == "food" and c.get("subtype") == "restaurant"]
    # The "cafe" slot is food-only (cafe / fast food / dessert). Newer POI
    # categories (museums, shops, wellness...) must not land in this slot —
    # they belong in the second-activity filler path instead.
    cafes = [
        c for c in ranked
        if c.get("kind") in {"place", "food"}
        and c.get("subtype") in {"cafe", "food", "fast_food", "ice_cream"}
    ]
    restaurants.sort(key=lambda c: -float(c.get("final_score") or 0))
    cafes.sort(key=lambda c: -float(c.get("final_score") or 0))
    rest = restaurants[0] if restaurants else None
    cafe = cafes[0] if cafes else None
    if slots.get("food_priority") and float(slots.get("budget_inr") or 1000) >= 800:
        substantial = [
            c for c in restaurants
            if c.get("price_tier") in {"mid", "premium"} or not c.get("price_tier")
        ]
        if substantial:
            rest = substantial[0]  # best-scored sit-down restaurant
    return rest, cafe


def _heuristic_plan(ranked: list[dict], slots: dict, weather: dict) -> dict[str, Any]:
    budget = float(slots.get("budget_inr") or 1000)
    party = party_size(slots)
    hours = float(slots.get("duration_hours") or 4)
    rainy = bool(weather.get("rainy"))
    stay_home = bool(slots.get("stay_home"))

    walk = next((c for c in ranked if c.get("kind") == "place" and c.get("subtype") == "walk"), None)
    restaurant, cafe = _pick_dining(ranked, slots)
    streaming = next((c for c in ranked if c.get("watch_at_home") or c.get("subtype") == "streaming"), None)
    _movies = [c for c in ranked if c.get("kind") == "movie" and not c.get("watch_at_home")]
    movie = _pick_best_movie(_movies, slots)
    music = next((c for c in ranked if c.get("kind") == "music"), None)
    steps = []
    cost = 0
    dur = 0

    if stay_home:
        # --- Stay-at-home plan: streaming movie + music ---
        if streaming:
            streaming_info = ""
            if streaming.get("streaming"):
                streaming_info = f" (available on {', '.join(streaming['streaming'][:2])})"
            steps.append(
                {
                    "order": 1,
                    "kind": "streaming",
                    "title": streaming["title"] + streaming_info,
                    "duration_min": int(streaming.get("duration_min") or 120),
                    "cost_inr": 0,
                    "flexible": False,
                    "genres": streaming.get("genres") or [],
                    "original_language": streaming.get("original_language"),
                    "why": "Watch at home — no need to go out. Streaming for free on your existing subscriptions.",
                }
            )
            dur += int(streaming.get("duration_min") or 120)
        if music:
            steps.append(
                {
                    "order": len(steps) + 1,
                    "kind": "music",
                    "title": music["title"],
                    "duration_min": 20,
                    "cost_inr": 0,
                    "flexible": True,
                    "why": "Relaxing background music for a cozy night in.",
                }
            )
            dur += 20
        explanation = (
            f"A cozy night in matching your {(slots.get('current_mood') or 'low-energy')} mood. "
            f"No going out needed — stream at home, ₹0 cost, perfect for unwinding."
        )
    else:
        # --- Go-out plan (original logic) ---
        if not rainy and walk:
            steps.append(
                {
                    "order": 1,
                    "kind": "walk",
                    "title": walk["title"],
                    "duration_min": 20,
                    "cost_inr": 0,
                    "flexible": False,
                    "why": "Low-effort reset after college; nearby.",
                }
            )
            dur += 20
        elif rainy:
            steps.append(
                {
                    "order": 1,
                    "kind": "indoor",
                    "title": "Short indoor pause at a quiet cafe (rain)",
                    "duration_min": 15,
                    "cost_inr": 0,
                    "flexible": True,
                    "why": "Live weather is wet — skip exposed walking.",
                }
            )
            dur += 15
        if restaurant:
            est = int(restaurant.get("estimated_cost") or 350) * party
            cap = budget if slots.get("food_priority") else 500 * party
            rcost = min(cap, est)
            cuisine_note = f" ({restaurant.get('cuisine')})" if restaurant.get("cuisine") else ""
            food_why = f"Nearby restaurant matching your mood{cuisine_note}."
            if slots.get("food_priority"):
                tier = restaurant.get("price_tier")
                tier_note = "a proper, filling meal" if tier in {"mid", "premium"} else "something quick and filling"
                food_why = f"Food's the main thing for you{cuisine_note} — {tier_note} at a well-rated nearby spot."
            steps.append(
                {
                    "order": len(steps) + 1,
                    "kind": "restaurant",
                    "title": restaurant["title"] + cuisine_note,
                    "duration_min": int(restaurant.get("duration_min") or 60),
                    "cost_inr": rcost,
                    "flexible": True,
                    "price_is_estimate": bool(restaurant.get("price_is_estimate")),
                    "price_tier": restaurant.get("price_tier"),
                    "opening_note": restaurant.get("opening_note"),
                    "why": food_why,
                }
            )
            cost += rcost
            dur += int(restaurant.get("duration_min") or 60)
        elif cafe:
            food_cost = min(300, int(cafe.get("estimated_cost") or 250)) * party
            steps.append(
                {
                    "order": len(steps) + 1,
                    "kind": "cafe",
                    "title": cafe["title"],
                    "duration_min": 45,
                    "cost_inr": food_cost,
                    "flexible": True,
                    "price_is_estimate": bool(cafe.get("price_is_estimate")),
                    "price_tier": cafe.get("price_tier"),
                    "opening_note": cafe.get("opening_note"),
                    "why": f"{_venue_descriptor(cafe).capitalize()} for a low-key evening.",
                }
            )
            cost += food_cost
            dur += 45
        if movie:
            mcost = int(movie.get("estimated_cost") or 220) * party
            is_est = bool(movie.get("is_estimate"))
            info = " (est.)" if is_est else ""
            steps.append(
                {
                    "order": len(steps) + 1,
                    "kind": "movie",
                    "title": movie["title"] + info,
                    "duration_min": int(movie.get("duration_min") or 130),
                    "cost_inr": mcost,
                    "flexible": False,
                    "runtime_source": movie.get("runtime_source") or ("estimate" if is_est else "data"),
                    "is_estimate": is_est,
                    "runtime_min_real": movie.get("runtime_min_real"),
                    "venue": movie.get("venue"),
                    "showtime_estimated": bool(movie.get("showtime_estimated")),
                    "showtime_disclaimer": movie.get("showtime_disclaimer"),
                    "genres": movie.get("genres") or [],
                    "genre_source": movie.get("genre_source") or "unknown",
                    "genre_fit": movie.get("genre_fit") or "unknown",
                    "mood_fit_verified": bool(movie.get("mood_fit_verified")),
                    "why": _movie_blurb(movie, slots),
                }
            )
            cost += mcost
            dur += int(movie.get("duration_min") or 130)
        if music:
            steps.append(
                {
                    "order": len(steps) + 1,
                    "kind": "music",
                    "title": music["title"],
                    "duration_min": 20,
                    "cost_inr": 0,
                    "flexible": True,
                    "why": _music_why(steps),
                }
            )
            dur += 20
        explanation = (
            f"Recommended because it matches a {(slots.get('current_mood') or 'low-energy')} mood, "
            f"stays near ₹{int(budget)}, fits about {hours:g} hours, and avoids high-intensity / crowded options."
        )

    return {
        "steps": steps,
        "total_cost_inr": cost,
        "total_duration_min": dur,
        "explanation": explanation,
        "uncertainty": [],
        "_agent": "heuristic-planner",
    }


# Kinds that physically occupy a place (need travel to/from the next stop).
_PHYSICAL_KINDS = {"walk", "cafe", "food", "restaurant", "movie", "cinema", "indoor", "place"}

# Kinds whose duration is a FACT that budget-fit may never rewrite: movie runtime
# (from data/TMDB) and travel time (from routing). Everything else (cafe dwell
# time, restaurant meal, place visit, music session, rest filler) is flexible
# and the only thing the budget-fit loop is allowed to stretch/shrink.
_FIXED_KINDS = {"movie", "streaming", "walk", "travel"}

# Fine-grained venue buckets used by the diversity pass to detect and break
# back-to-back same-type stops (e.g. two cafes in a row).
_VENUE_CLASS_KEYWORDS = {
    "dessert": ("ice_cream", "dessert", "sweets", "parlour", "dairy", "gelato", "kulfi", "falooda", "sweet"),
    "snack": ("fast_food", "farsan", "snacks", "chaat", "tiffin", "stall", "kiosk", "roll", "sandwich", "snack"),
    "cafe": ("cafe", "coffee", "tea", "coffeeshop", "teahouse"),
}


def _venue_class(step: dict) -> str:
    """Classify a step or ranked candidate into a broad venue bucket."""
    kind = str(step.get("kind") or "").lower()
    subtype = str(step.get("subtype") or "").lower()
    title = str(step.get("title") or "").lower()
    blob = f"{kind} {subtype} {title}"
    if kind in {"movie", "cinema"}:
        return "cinema"
    if kind == "streaming":
        return "streaming"
    if kind == "music":
        return "music"
    if kind in {"rest", "buffer", "indoor"}:
        return "rest"
    if kind == "book":
        return "book"
    if kind == "walk" or subtype == "walk":
        return "walk"
    if kind == "restaurant" or subtype == "restaurant":
        return "restaurant"
    for cls, words in _VENUE_CLASS_KEYWORDS.items():
        if any(w in blob for w in words):
            return cls
    if kind in {"food", "place", "cafe"}:
        return "place"
    return "other"


def _swap_step_kind(cand: dict) -> str:
    """Derive a plan-step ``kind`` value from a ranked candidate."""
    kind = cand.get("kind") or ""
    subtype = str(cand.get("subtype") or "").lower()
    if kind == "walk" or subtype == "walk":
        return "walk"
    if subtype == "restaurant" or kind == "restaurant":
        return "restaurant"
    if kind in {"food", "place", "cafe"}:
        return "cafe"
    if kind == "music":
        return "music"
    if kind == "book":
        return "book"
    return kind or "place"


def _diversity_why(cand: dict, orig_cls: str) -> str:
    desc = _venue_descriptor(cand)
    return f"Swapped for variety — {desc} instead of two {orig_cls} stops back-to-back."


def _diversify_consecutive_stops(
    plan: dict,
    ranked: list[dict],
    slots: dict,
    weather: dict,
    budget: float,
    minutes: float,
) -> dict:
    """If two adjacent physical stops share a venue class, try swapping the
    second for a nearby alternative of a *different* class, keeping the
    original's duration unchanged so the budget fit stays valid.  No-op if
    no suitable swap exists near the original stop."""
    steps = plan.get("steps", [])
    if not steps:
        return plan
    physical_idx = [i for i, s in enumerate(steps) if s.get("kind") in _PHYSICAL_KINDS]
    if len(physical_idx) < 2:
        return plan
    used_titles = {(s.get("title") or "").strip().lower() for s in steps}

    for pos in range(len(physical_idx) - 1):
        i = physical_idx[pos]
        j = physical_idx[pos + 1]
        s_i, s_j = steps[i], steps[j]
        cls_i = _venue_class(s_i)
        cls_j = _venue_class(s_j)
        if cls_i != cls_j:
            continue
        # Never swap hard/fixed categories — movies carry showtimes/runtime,
        # streaming is at-home, music is always last, rest is padding.
        if cls_i in ("cinema", "streaming", "music", "rest"):
            continue
        cls_next = (
            _venue_class(steps[physical_idx[pos + 2]])
            if pos + 2 < len(physical_idx)
            else None
        )
        orig_dist = s_j.get("distance_km")
        orig_dur = int(s_j.get("duration_min") or 0)
        orig_cost = int(s_j.get("cost_inr") or 0)

        for cand in ranked:
            c_cls = _venue_class(cand)
            if c_cls == cls_i:
                continue
            if cls_next is not None and c_cls == cls_next:
                continue  # avoid creating a new adjacent duplicate
            if cand.get("kind") not in _PHYSICAL_KINDS:
                continue
            if cand.get("kind") in ("movie",):
                continue  # don't inject a movie as a diversity swap
            c_title = (cand.get("title") or "").strip().lower()
            if not c_title or c_title in used_titles:
                continue
            if not hard_filter(cand, slots, weather, budget, minutes):
                continue
            c_dist = cand.get("distance_km")
            if orig_dist is not None and c_dist is not None:
                max_dist = max(orig_dist * 1.8, 3.0)
                if c_dist > max_dist:
                    continue

            steps[j] = {
                "order": s_j.get("order", j + 1),
                "kind": _swap_step_kind(cand),
                "title": cand.get("title"),
                "duration_min": orig_dur,
                "cost_inr": min(orig_cost, int(cand.get("estimated_cost") or 0) * party_size(slots)),
                "flexible": True,
                "price_is_estimate": bool(cand.get("price_is_estimate")),
                "price_tier": cand.get("price_tier"),
                "opening_note": cand.get("opening_note"),
                "why": _diversity_why(cand, cls_i),
                "_lat": cand.get("lat"),
                "_lon": cand.get("lon"),
                "distance_km": cand.get("distance_km"),
                "distance_label": _fmt_km(cand.get("distance_km")),
                "walk_min": _walk_min(cand.get("distance_km")),
            }
            used_titles.add(c_title)
            break
    return plan


def _kind_flexible(kind: str | None) -> bool:
    return kind not in _FIXED_KINDS


def _is_flexible(step: dict) -> bool:
    return bool(step.get("flexible", _kind_flexible(step.get("kind"))))


# Realistic upper bound on dwelling at a flexible stop.  Without these caps,
# the budget-fit loop can dump an entire leftover gap into a single cafe/place
# step (e.g. a 4-5h request inflating one cafe to ~190 min).
_DUR_CAPS = {
    "restaurant": 90, "cafe": 90, "food": 90, "place": 90,
    "indoor": 60, "book": 60, "rest": 45, "music": 30,
}


# At most this many generic rest/filler blocks may appear in one plan. Several
# back-to-back buffers read as repeated filler rather than a real itinerary.
_MAX_REST_BLOCKS = 1


def _limit_rest_filler(plan: dict, max_rest_blocks: int = _MAX_REST_BLOCKS) -> dict:
    """Collapse multiple generic rest blocks down to one, keeping time truthful.

    A long request can leave genuine shortfall once every real stop is at its
    per-kind cap; that leftover is honest, but repeating it as three identical
    buffers is not. So we keep ONE rest block and re-home the removed minutes
    onto the last FLEXIBLE step that still has headroom under _DUR_CAPS.

    We deliberately never stretch a fixed step (movie runtime, travel, walk):
    doing so is what produced the earlier "260-minute cafe" style bug. Any
    minutes that no flexible step can absorb stay in the single retained buffer
    so the plan total never silently under-fills the user's request.
    """
    steps = plan.get("steps") or []
    rest_idx = [i for i, s in enumerate(steps) if s.get("kind") == "rest"]
    if len(rest_idx) <= max_rest_blocks:
        return plan

    keep = rest_idx[0]
    drop = rest_idx[max_rest_blocks:]
    freed = sum(int(steps[i].get("duration_min") or 0) for i in drop)
    steps = [s for i, s in enumerate(steps) if i not in set(drop)]

    # Re-home freed time onto the last flexible step with headroom.
    for s in reversed(steps):
        if freed <= 0:
            break
        if s.get("kind") == "rest" or not _is_flexible(s):
            continue
        cap = _DUR_CAPS.get(s.get("kind"))
        if not cap:
            continue
        headroom = cap - int(s.get("duration_min") or 0)
        if headroom <= 0:
            continue
        add = min(headroom, freed)
        s["duration_min"] = int(s.get("duration_min") or 0) + add
        freed -= add

    # Whatever no flexible step could absorb stays in the retained buffer, so
    # the plan still covers the requested duration (flagged as an estimate).
    if freed > 0 and keep < len(steps):
        retained = next((s for s in steps if s.get("kind") == "rest"), None)
        if retained is not None:
            retained["duration_min"] = int(retained.get("duration_min") or 0) + freed
            retained["title"] = "Remaining free time"
            retained["why"] = (
                "Unfilled time after every stop reached its realistic length. "
                "Kept as free time rather than stretching one activity to an "
                "unrealistic length."
            )
            retained["is_remainder"] = True

    for n, s in enumerate(steps):
        s["order"] = n + 1
    plan["steps"] = steps
    plan["total_duration_min"] = int(sum(int(s.get("duration_min") or 0) for s in steps))
    plan["total_cost_inr"] = int(sum(int(s.get("cost_inr") or 0) for s in steps))
    return plan


def _clamp_step_duration(step: dict) -> dict:
    """Clamp a FLEXIBLE stop's dwell time to its per-kind cap. Fixed steps
    (movie runtime, streaming runtime, walk, travel) are never rewritten."""
    if not _is_flexible(step):
        return step
    cap = _DUR_CAPS.get(step.get("kind"))
    if cap and int(step.get("duration_min") or 0) > cap:
        step["duration_min"] = cap
    return step


def _clamp_plan_durations(plan: dict) -> dict:
    """Normalize over-long flexible steps up front (e.g. an LLM dropout),
    before travel legs are computed and the budget loop redistributes time
    within the caps."""
    for step in plan.get("steps", []):
        _clamp_step_duration(step)
    return plan


def _tag_flexibility(plan: dict) -> dict:
    """Tag every step's duration as fixed or flexible (LLM plans carry no flag)."""
    for step in plan.get("steps", []):
        step.setdefault("flexible", _kind_flexible(step.get("kind")))
    return plan


def _ensure_explicit_movie(plan: dict, movie_pool: list[dict], slots: dict) -> dict:
    """Honour an explicit 'watch a movie' request even when the primary planner
    dropped the film (e.g. LLM plan omitted it, or the genre gate excluded every
    candidate). Injects the best-available movie candidate as a step so the
    user's stated instruction is never silently ignored; the blurb carries an
    honest disclaimer when the tone couldn't be verified."""
    if not slots.get("want_movie"):
        return plan
    if any(s.get("kind") in {"movie", "streaming"} for s in plan.get("steps", [])):
        return plan
    pool = [c for c in movie_pool if c.get("kind") == "movie" and not c.get("watch_at_home")]
    pick = _pick_best_movie(pool, slots)
    if not pick:
        return plan
    steps = plan.get("steps", [])
    movie_step = {
        "order": 0,
        "kind": "movie",
        "title": pick.get("title") or "A movie",
        "duration_min": int(pick.get("duration_min") or 130),
        "cost_inr": int(pick.get("estimated_cost") or 220) * party_size(slots),
        "flexible": False,
        "runtime_source": pick.get("runtime_source") or "estimate",
        "is_estimate": bool(pick.get("is_estimate")),
        "runtime_min_real": pick.get("runtime_min_real"),
        "venue": pick.get("venue"),
        "showtime_estimated": bool(pick.get("showtime_estimated")),
        "showtime_disclaimer": pick.get("showtime_disclaimer"),
        "genres": pick.get("genres") or [],
        "genre_source": pick.get("genre_source") or "unknown",
        "genre_fit": pick.get("genre_fit") or "unknown",
        "mood_fit_verified": bool(pick.get("mood_fit_verified")),
        "original_language": pick.get("original_language"),
        "why": _movie_blurb(pick, slots),
    }
    # Place the film in its natural timeline slot: BEFORE any trailing wind-down
    # music or rest leg, so a music step never precedes the film it references.
    trail = [i for i, s in enumerate(steps) if s.get("kind") in {"music", "rest"}]
    pos = trail[0] if trail else len(steps)
    steps.insert(pos, movie_step)
    plan["steps"] = steps
    plan["total_duration_min"] = int(sum(int(s.get("duration_min") or 0) for s in steps))
    plan["total_cost_inr"] = int(sum(int(s.get("cost_inr") or 0) for s in steps))
    return plan


def _movie_request_note(plan: dict, slots: dict) -> str:
    """Plain-language note when an explicit movie request couldn't be fully
    honoured, so the user is told rather than left wondering why there's no
    film (or why the film is a best-guess)."""
    if not slots.get("want_movie"):
        return ""
    mv = next((s for s in plan.get("steps", []) if s.get("kind") == "movie"), None)
    if mv is None:
        return (
            " You asked to watch a movie, but no showing could be confirmed nearby — "
            "I built the rest of the plan around your other preferences instead."
        )
    if not mv.get("mood_fit_verified"):
        return (
            " Note: the movie's genre/tone couldn't be fully verified from listings, "
            "so it's a best-guess match — double-check the listing before booking."
        )
    return ""


def _normalize_movie_steps(plan: dict, ranked: list[dict], slots: dict | None = None) -> dict:
    """Attach REAL runtime + showtime disclaimer + fixed flag to every movie /
    streaming step, no matter which planner produced it.

    Each movie step is matched back to a ranked candidate (real map cinema with
    a runtime resolved from TMDB, or a streaming candidate). The step's duration
    is pinned from the candidate's real runtime and flagged FIXED so the
    budget-fit loop can never rewrite a film's actual runtime. If no real runtime
    is known (e.g. no TMDB key), the step is marked as an estimate and the
    showtime is surfaced as an estimate rather than a fabricated fact.
    """
    movies = [c for c in ranked if c.get("kind") == "movie"]
    for step in plan.get("steps", []):
        if step.get("kind") not in {"movie", "streaming"}:
            continue
        title = (step.get("title") or "").replace("(est.)", "").strip()
        tlow = title.lower()
        matches = [
            c for c in movies
            if (c.get("title") or "").lower()
            and ((c.get("title") or "").lower() in tlow or tlow in (c.get("title") or "").lower())
        ]
        # Prefer a cinema-paired candidate (it carries the venue + showtime
        # disclaimer); otherwise fall back to any matching movie candidate.
        cand = (next((c for c in matches if c.get("venue")), None)
                or (matches[0] if matches else None))
        real = (cand or {}).get("runtime_min_real")
        rt_tmdb = None
        if not real:
            rt = providers.movie_runtime_by_title(title)
            real = rt.get("runtime_min")
            rt_tmdb = rt.get("tmdb_id")
            if real:
                cand = cand or {**rt, "venue": None if cand is None else cand.get("venue")}
        if real:
            step["duration_min"] = int(real)
            step["runtime_source"] = "tmdb"
            step["is_estimate"] = False
            step["runtime_min_real"] = int(real)
        else:
            step["duration_min"] = int((cand or {}).get("duration_min") or step.get("duration_min") or 130)
            step["runtime_source"] = "estimate"
            step["is_estimate"] = True
            step["runtime_min_real"] = None
        step["flexible"] = False
        if cand:
            if cand.get("venue"):
                step["venue"] = cand.get("venue")
            step["showtime_estimated"] = bool(cand.get("showtime_estimated"))
            step["showtime_disclaimer"] = cand.get("showtime_disclaimer")
            if cand.get("genre_source") and cand.get("genres"):
                step["genres"] = cand.get("genres")
                step["genre_source"] = cand.get("genre_source")
                step["genre_fit"] = cand.get("genre_fit") or "unknown"
                step["mood_fit_verified"] = bool(cand.get("mood_fit_verified"))
                step["why"] = _movie_blurb(cand, slots or {})
            # Carry the real original-language code from TMDB onto the step so
            # a later happy reaction can learn "Prefers Hindi-language movies".
            if cand.get("original_language"):
                step["original_language"] = cand.get("original_language")
            # Same film can usually also be watched at home — surface the TMDB
            # streaming options next to the cinema showtime. Lazy: only resolved
            # for the movie(s) actually chosen into the plan, and only when we
            # already hold a confident TMDB id (never fabricated).
            step_tmdb = (cand or {}).get("tmdb_id") or rt_tmdb
            if step_tmdb and not step.get("streaming"):
                _wp = providers.tmdb_watch_providers(int(step_tmdb))
                _flat = [p.get("name") for p in ((_wp or {}).get("flatrate") or [])[:3]]
                if _flat or (_wp or {}).get("link"):
                    step["streaming"] = _flat
                    step["watch_link"] = (_wp or {}).get("link")
    return plan


def _attach_coordinates_to_steps(plan: dict, ranked: list[dict], lat: float, lon: float) -> dict:
    """Attach real venue coords (from ranked candidates) to each plan step.

    Unmatched physical steps fall back to the user's origin so travel legs can
    still be computed from the map data the tools returned.
    """
    for step in plan.get("steps", []):
        step.setdefault("_lat", None)
        step.setdefault("_lon", None)
        if step.get("kind") == "travel":
            continue
        title = (step.get("title") or "").lower()
        for item in ranked:
            it = (item.get("title") or "").lower()
            if it and (it in title or title in it) and item.get("lat") is not None:
                step["_lat"] = float(item["lat"])
                step["_lon"] = float(item["lon"])
                step.setdefault("distance_km", item.get("distance_km"))
                break
        if step.get("kind") in _PHYSICAL_KINDS and step.get("_lat") is None:
            step["_lat"] = float(lat)
            step["_lon"] = float(lon)
    return plan


def _venue_descriptor(cand: dict) -> str:
    """A venue-type phrase for a place/food candidate so step blurbs never
    default to 'a nearby spot' for a dairy parlour or 'comfort food' for a
    dessert stop — the wording reflects what the venue actually is."""
    subtype = str(cand.get("subtype") or "").lower()
    name = (cand.get("title") or "").strip().lower()
    blob = f"{subtype} {name}"
    if any(w in blob for w in (
        "ice_cream", "dessert", "sweets", "parlour", "dairy", "ice cream",
        "sweet", "kulfi", "falooda", "gelato",
    )):
        return "a dessert/sweets spot"
    if any(w in blob for w in (
        "fast_food", "farsan", "snacks", "tiffin", "snack", "chaat", "stall",
        "kiosk", "roll", "sandwich",
    )):
        return "a quick snack spot"
    if subtype == "restaurant" or any(w in blob for w in (
        "restaurant", "dining", "bistro", "hotel",
    )):
        return "a sit-down restaurant"
    if subtype == "cafe" or any(w in blob for w in (
        "cafe", "coffee", "tea", "coffeeshop",
    )):
        return "a quiet cafe"
    return "a nearby spot"


def _music_why(steps: list[dict], lang: str | None = None) -> str:
    """Context-aware blurb for a wind-down music leg: references what actually
    precedes it in the plan instead of hardcoding 'after the film'."""
    kinds = [s.get("kind") for s in (steps or [])]
    lang_note = f"{lang} " if lang and lang != "english" else ""
    if "movie" in kinds or "streaming" in kinds:
        return f"Calming {lang_note}playlist after the film to bring the evening down gently."
    if "restaurant" in kinds or "cafe" in kinds:
        return f"Calming {lang_note}playlist while you wind down after your meal."
    return f"Calming {lang_note}background music to help you settle into the evening."


def _attach_music_tracks(plan: dict, music: list[dict]) -> None:
    """Attach the live Spotify tracks to every music step
    so the plan surfaces real mood-based recommendations, not a template label.

    The step's duration is reconciled to the REAL playlist length (sum of the
    attached tracks' durations) so the UI never shows e.g. "45 min" next to a
    4-song, 14-minute playlist. Plan totals are recomputed afterwards to stay
    internally consistent, and any time lost by the accurate playlist length is
    soaked back into the most flexible non-music step so the requested duration
    is still honoured.
    """
    live = [t for t in (music or []) if t and t.get("title")]
    music_steps = [s for s in (plan.get("steps") or []) if s.get("kind") == "music"]
    if not live:
        # Music is Spotify-only. If Spotify returned nothing we must NOT show a
        # fabricated playlist — flag the leg honestly and leave the plan valid.
        for s in music_steps:
            s["tracks"] = []
            s["tracks_source"] = "spotify (no match)"
            s["unavailable"] = True
        return
    # Tracks already used by an earlier music leg in THIS plan must not be
    # reused, otherwise two legs in one plan show the same songs.
    from moodos.spotify import _track_key

    used_in_plan: set[str] = set()
    for step_no, s in enumerate(music_steps):
        target = max(1, int(s.get("duration_min") or 0) or 30)
        # Rotate the pool per music step so two music legs never show the
        # identical track list (they'd otherwise both start from live[0]).
        offset = (step_no * 3) % len(live)
        pool = live[offset:] + live[:offset]
        sel: list[dict] = []
        total_sec = 0
        seen: set = set()
        for t in pool:
            key = _track_key(t)
            if key in seen or key in used_in_plan:
                continue
            seen.add(key)
            sec = int(t.get("duration_sec") or 0)
            sel.append(t)
            total_sec += sec
            if total_sec >= target * 60 and len(sel) >= 5:
                break
        if not sel:
            # Pool is exhausted (everything already used by a previous leg).
            # Re-fall back to the whole pool rather than showing an empty leg.
            sel = [t for t in live if _track_key(t) not in seen]
            total_sec = sum(int(t.get("duration_sec") or 0) for t in sel)
        if not sel:
            sel = live[:8]
            total_sec = sum(int(t.get("duration_sec") or 0) for t in sel)
        used_in_plan.update(_track_key(t) for t in sel)
        total_sec = sum(int(t.get("duration_sec") or 0) for t in sel)
        s["tracks"] = sel
        s["tracks_source"] = "spotify (live search, mood-matched)"
        s["playlist_duration_min"] = round(total_sec / 60, 1)
        if total_sec:
            s["duration_min"] = max(1, int(round(total_sec / 60)))
        if "mix" in str(s.get("title")).lower():
            # Title the mix after a track that is actually IN this step, so
            # distinct music legs get distinct names.
            base = sel[0]["title"].split(" — ")[0] if sel else live[0]["title"].split(" — ")[0]
            s["title"] = f"{base} — calm wind-down mix"

    # Keep the plan totals the single source of truth (duration == sum of steps).
    plan["total_duration_min"] = int(sum(int(x.get("duration_min") or 0) for x in plan["steps"]))
    plan["total_cost_inr"] = int(sum(int(x.get("cost_inr") or 0) for x in plan["steps"]))
    requested = int(plan.get("requested_minutes") or 0)
    tol = int(plan.get("budget_fit", {}).get("tolerance_min") or 0)
    if requested and plan["steps"]:
        diff = plan["total_duration_min"] - requested
        if diff < 0 and -diff > tol + 1:
            flex = [
                x for x in plan["steps"]
                if _is_flexible(x) and x.get("kind") not in {"travel", "music"}
            ]
            if flex:
                top = max(flex, key=lambda x: int(x.get("duration_min") or 0))
                # Never push a step past its realistic dwell cap when soaking
                # time back in; add capped buffers for any remainder instead.
                cap = _DUR_CAPS.get(top.get("kind"), 120)
                cur = int(top.get("duration_min") or 0)
                take = min(-diff, max(0, cap - cur))
                if take:
                    top["duration_min"] = cur + take
                    _add_buffer_steps(plan, -diff - take)
                else:
                    _add_buffer_steps(plan, -diff)
                plan["total_duration_min"] = int(
                    sum(int(x.get("duration_min") or 0) for x in plan["steps"])
                )
        plan["budget_fit"].update(
            _budget_fit(plan, requested, _BUDGET_TOL_FRACTION * requested)
        )


def _best_filler(plan: dict, ranked: list[dict], shortfall: int, slots: dict | None = None) -> tuple[dict | None, bool]:
    """Pick the best MEANINGFUL flexible filler for leftover time, preferring an
    actual activity over generic rest padding.

    Preference order:
    1. a wind-down music / ambient leg (non-physical, no travel) — if the plan
       doesn't already have one;
    2. a second short mood-aligned activity pulled from the candidate pool that
       isn't already in the plan (physical — caller must add a travel leg);
    3. a SINGLE bare buffer step, only if the remaining gap is >= ~5 min and no
       bare buffer exists yet.

    Returns (filler_step_or_None, needs_travel).
    """
    used = {(s.get("title") or "").strip().lower() for s in plan["steps"]}
    has_music = any(s.get("kind") == "music" for s in plan["steps"])
    has_bare = any(s.get("kind") == "rest" for s in plan["steps"])
    lang = ((slots or {}).get("music_language") or "").strip() or None

    # 1) Wind-down music leg — a meaningful, non-physical filler.
    if not has_music and shortfall >= 10:
        if lang and lang != "english":
            title = f"Calm {lang} wind-down music / ambient mix"
        else:
            title = "Chill wind-down music / ambient mix"
        return ({
            "kind": "music",
            "title": title,
            "duration_min": min(shortfall, 30),
            "cost_inr": 0,
            "flexible": True,
            "lang": lang,
            "why": _music_why(plan["steps"], lang),
        }, False)

    # 2) Second short mood-aligned activity from the pool (not already used).
    for cand in ranked:
        ctitle = (cand.get("title") or "").strip().lower()
        if not ctitle or ctitle in used:
            continue
        ckind = cand.get("kind")
        if ckind in {"place", "food", "cafe"}:
            vname = (cand.get("title") or "").strip()
            vtext = (cand.get("text") or "").strip()
            desc = _venue_descriptor(cand)
            extra = ""
            if vtext:
                ex = vtext
                if vname:
                    ex = re.sub(re.escape(vname), "", ex, flags=re.IGNORECASE)
                ex = re.sub(
                    r"\b(cafe|restaurant|food|fast food|ice cream|ice_cream|parlour|"
                    r"stall|snacks|farsan|sweets|dessert|eating place|eatery)\b",
                    "", ex, flags=re.IGNORECASE,
                )
                ex = ex.strip(" .,-—–:;()").strip()
                if ex:
                    extra = f" ({ex})"
            why = (
                f"Round out the evening with {desc} at {vname}{extra} — a real, "
                f"nearby option that fits a relaxed mood."
            )
            return ({
                "kind": "place" if ckind == "place" else "cafe",
                "title": cand.get("title"),
                "duration_min": min(shortfall, 30),
                "cost_inr": int(cand.get("estimated_cost") or 0) * party_size(slots),
                "flexible": True,
                "why": why,
                "lat": cand.get("lat"),
                "lon": cand.get("lon"),
            }, True)

    # 3) Single bare buffer — only if enough of a gap and none already placed.
    if shortfall >= 5 and not has_bare:
        return ({
            "kind": "rest",
            "title": "Relaxed pacing / rest",
            "duration_min": min(shortfall, 10),
            "cost_inr": 0,
            "flexible": True,
            "why": "Buffer time so the evening feels unhurried and matches your time budget.",
        }, False)
    return None, False


# Distinct filler flavours so a long request does not produce N identical
# "Unhurried pacing" rows stacked on top of each other.
_BUFFER_VARIANTS = (
    ("Settling in / unhurried pause",
     "A breather between stops so the evening does not feel rushed."),
    ("Window to wander nearby",
     "Spare time to look around the area and pick something up on the way."),
    ("Slow stretch, no plans",
     "Deliberate idle time — no obligation to be anywhere else yet."),
    ("Coffee and a breather",
     "A short pause to reset before the next part of the evening."),
    ("Time to simply sit",
     "Space to rest and let the mood settle before moving on."),
    ("Free time, your call",
     "Unscheduled time you can use however you like."),
)


def _add_buffer_steps(plan: dict, shortfall: int, max_buffers: int = 6) -> int:
    """Absorb leftover time with additional capped pacing buffers.

    Used only when every real flexible stop is already at its per-kind cap, so
    the request (e.g. a 5-8h evening) cannot be met without padding. Each buffer
    respects _DUR_CAPS['rest'], so a long request never produces one absurd
    multi-hour step. Returns the minutes actually consumed.
    """
    if shortfall <= 0:
        return 0
    cap = _DUR_CAPS.get("rest", 45)
    consumed = 0
    # Vary the buffer wording so several buffers in one plan read as distinct
    # parts of the evening instead of N identical "Unhurried pacing" rows.
    # We keep every buffer (dropping them would silently shrink the plan below
    # the user's requested duration) and instead interleave them with real,
    # already-fetched places so the timeline never stacks filler back-to-back.
    filler = _BUFFER_VARIANTS[:]
    idx = 0
    while shortfall > 0 and max_buffers > 0:
        chunk = min(shortfall, cap)
        title, why = filler[idx % len(filler)]
        plan["steps"].append({
            "order": len(plan["steps"]) + 1,
            "kind": "rest",
            "title": title,
            "duration_min": chunk,
            "cost_inr": 0,
            "flexible": True,
            "why": why,
        })
        shortfall -= chunk
        consumed += chunk
        max_buffers -= 1
        idx += 1
    return consumed


def _collapse_rest_buffers(plan: dict) -> dict:
    """Merge runs of adjacent generic rest buffers, never exceeding the rest cap.

    A run of 3+ back-to-back buffers reads as repeated filler. We fold them
    together while the combined duration still fits inside _DUR_CAPS['rest'],
    which removes the visible repetition WITHOUT discarding time (dropping the
    blocks outright would silently under-fill the user's requested duration).
    If a run still exceeds the cap, it stays split rather than becoming one
    absurd multi-hour step. Totals are recomputed from the surviving steps.
    """
    steps = plan.get("steps", [])
    cap = _DUR_CAPS.get("rest", 45)
    out: list[dict] = []
    for s in steps:
        if s.get("kind") == "rest" and out and out[-1].get("kind") == "rest":
            prev = out[-1]
            combined = int(prev.get("duration_min") or 0) + int(s.get("duration_min") or 0)
            if combined <= cap:
                prev["duration_min"] = combined
                continue
        out.append(s)
    for n, s in enumerate(out):
        s["order"] = n + 1
    # Last-resort guard: never show the same buffer title twice in one plan.
    seen_buffer_titles: set[str] = set()
    for s in out:
        if s.get("kind") != "rest":
            continue
        t = str(s.get("title") or "").strip().lower()
        if not t:
            continue
        if t in seen_buffer_titles:
            for alt_title, alt_why in _BUFFER_VARIANTS:
                if alt_title.lower() not in seen_buffer_titles:
                    s["title"] = alt_title
                    s["why"] = alt_why
                    t = alt_title.lower()
                    break
        seen_buffer_titles.add(t)
    plan["steps"] = out
    plan["total_duration_min"] = int(sum(int(s.get("duration_min") or 0) for s in out))
    plan["total_cost_inr"] = int(sum(int(s.get("cost_inr") or 0) for s in out))
    return plan


def _travel_leg_for(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    """Build a travel leg between two stops: mode, distance (km), duration, ₹cost.

    Uses real route data from the LocationService (OSRM driving + walking) when
    available; otherwise a clearly-flagged haversine estimate. The route source
    is surfaced on the leg so the UI can label "mapped" vs "estimate".
    """
    route = location_service.calculate_route(lat1, lon1, lat2, lon2)
    km = round(max(route["distance_km"], 0.15), 2)
    drive_min = route.get("drive_min")
    walk_min = route.get("walk_min")
    if route.get("source") == "osrm":
        if km < 1.4 or (walk_min is not None and walk_min <= 35):
            mode, dur, why, src = "walk", max(4, int(walk_min or 0)), \
                "Short hop — walkable route matched on the map.", "osrm"
        elif km < 9 and drive_min is not None:
            mode, dur, why, src = "drive", max(6, int(drive_min)), \
                "Route matched from road data.", "osrm"
        else:
            mode, dur, why, src = "transit", max(14, int(drive_min or km * 3.2)), \
                "Farther apart — take a bus/metro (~₹30) between stops.", "osrm"
    else:
        if km < 1.5:
            mode, dur, why, src = "walk", max(4, int(round(km * 12))), \
                "Short hop — walkable between stops (estimate).", "estimate"
        elif km < 6:
            mode, dur, why, src = "drive", max(6, int(round(km * 1.6))), \
                "A few km apart — short auto/ride between stops (estimate).", "estimate"
        else:
            mode, dur, why, src = "transit", max(14, int(round(km * 3.2))), \
                "Farther apart — take a bus/metro (~₹30) between stops (estimate).", "estimate"
    return {
        "kind": "travel",
        "mode": mode,
        "title": f"Travel by {mode}",
        "duration_min": dur,
        "cost_inr": 0,
        "flexible": False,
        "distance_km": km,
        "distance_label": _fmt_km(km),
        "route_source": src,
        "why": why,
    }


def _insert_travel_legs(plan: dict, ranked: list[dict], lat: float, lon: float) -> dict:
    """Insert a travel leg between every adjacent pair of physical stops."""
    _attach_coordinates_to_steps(plan, ranked, lat, lon)
    steps = [s for s in plan.get("steps", []) if s.get("kind") != "travel"]
    physical = [i for i, s in enumerate(steps) if s.get("kind") in _PHYSICAL_KINDS]
    insert_after: dict[int, list[dict]] = {}
    legs: list[dict] = []
    for i in range(len(physical) - 1):
        a = steps[physical[i]]
        b = steps[physical[i + 1]]
        leg = _travel_leg_for(
            a.get("_lat", lat), a.get("_lon", lon),
            b.get("_lat", lat), b.get("_lon", lon),
        )
        leg["from"] = (a.get("title") or "").strip()
        raw = (b.get("title") or "").strip()
        # Strip ALL leading travel prefixes (handles double nesting)
        prefixes_to_strip = (
            "Walk to ","Drive to ","Travel to ",
            "Ride to ","Take transit to ","Head to ",
        )
        for _ in range(3):  # max 3 passes to handle nesting
            stripped = False
            for p in prefixes_to_strip:
                if raw.startswith(p):
                    raw = raw[len(p):]
                    stripped = True
                    break
            if not stripped:
                break
        leg["to"] = raw
        legs.append(leg)
        insert_after.setdefault(physical[i], []).append(leg)
    out: list[dict] = []
    for idx, s in enumerate(steps):
        out.append(s)
        out.extend(insert_after.get(idx, []))
    for n, s in enumerate(out):
        s["order"] = n + 1
    plan["steps"] = out
    dur = sum(int(s.get("duration_min") or 0) for s in out)
    cost = sum(int(s.get("cost_inr") or 0) for s in out)
    plan["total_duration_min"] = dur
    plan["total_cost_inr"] = cost
    plan["has_travel_legs"] = bool(legs)
    return plan


def _finalize_step_order_and_blurbs(plan: dict) -> dict:
    """Lock the TRUE chronological order of the final step list and regenerate
    any position-dependent blurbs once ordering is final.

    Fixes two classes of bug:
      * steps numbered out of order (1, 3, 5...) when a step was injected late;
      * a music step whose blurb says 'after the film' but sits BEFORE the film.
    """
    steps = plan.get("steps", [])
    if not steps:
        return plan
    has_movie_or_stream = any(s.get("kind") in {"movie", "streaming"} for s in steps)
    has_meal = any(s.get("kind") in {"restaurant", "cafe", "food"} for s in steps)
    music_lang = next((s.get("lang") for s in steps if s.get("kind") == "music"), None)
    if has_movie_or_stream:
        music_why = _music_why(steps, music_lang)
    elif has_meal:
        music_why = _music_why(steps, music_lang)
    else:
        music_why = _music_why(steps, music_lang)
    for s in steps:
        if s.get("kind") == "music":
            s["why"] = music_why
    for n, s in enumerate(steps):
        s["order"] = n + 1
    plan["total_duration_min"] = int(sum(int(s.get("duration_min") or 0) for s in steps))
    plan["total_cost_inr"] = int(sum(int(s.get("cost_inr") or 0) for s in steps))
    return plan


def _fix_generic_place_names(plan: dict, ranked: list[dict]) -> dict:
    """Replace any LLM-invented generic place names with real
    ranked candidates. A step is considered generic when its title
    contains no word longer than 4 chars that matches any candidate title."""
    generic_markers = (
        "quiet cafe", "nearby cafe", "a cafe", "warm beverage",
        "light snack", "a restaurant", "nearby restaurant",
        "a place", "nearby place",
    )
    place_kinds = {"cafe", "food", "place", "restaurant"}
    real_candidates = [
        c for c in ranked
        if c.get("kind") in place_kinds
        and c.get("title")
        and not (c.get("title") or "").lower().startswith("nearby ")
    ]
    if not real_candidates:
        return plan
    used_titles = set()
    for step in plan.get("steps", []):
        if step.get("kind") not in place_kinds:
            continue
        title = (step.get("title") or "").lower()
        is_generic = any(marker in title for marker in generic_markers)
        if not is_generic:
            used_titles.add(title)
            continue
        # Find best unused real candidate
        for cand in real_candidates:
            ctitle = (cand.get("title") or "").strip()
            if ctitle.lower() not in used_titles:
                step["title"] = ctitle
                step["why"] = (
                    step.get("why") or
                    f"Real nearby spot matching your mood — {ctitle}."
                )
                used_titles.add(ctitle.lower())
                break
    return plan


def _remove_llm_travel_steps(plan: dict) -> dict:
    prefixes = ("walk to ","drive to ","travel to ",
                "ride to ","head to ")
    generic_walks = (
        "quiet, reflective walk", "reflective walk",
        "leisurely evening stroll", "evening stroll",
        "short stroll", "gentle walk", "peaceful walk",
        "quiet walk", "relaxing walk",
    )
    cleaned = []
    for s in plan.get("steps", []):
        title = (s.get("title") or "").lower().strip()
        kind = (s.get("kind") or "").lower()
        # Remove LLM travel steps
        if any(title.startswith(p) for p in prefixes):
            continue
        # Remove generic invented walk steps (no real place)
        if kind == "walk" and any(g in title for g in generic_walks):
            continue
        cleaned.append(s)
    plan["steps"] = cleaned
    plan["total_duration_min"] = int(
        sum(int(s.get("duration_min") or 0) for s in cleaned))
    plan["total_cost_inr"] = int(
        sum(int(s.get("cost_inr") or 0) for s in cleaned))
    return plan


_BUDGET_TOL_FRACTION = 0.03


def _budget_fit(plan: dict, requested_min: float, tol: float) -> dict[str, Any]:
    """actual_min / delta_min / within_tolerance for the plan's current steps.

    ``tol`` must be the EXACT (unrounded) tolerance in minutes - 0.03 of the
    requested window - because rounding first flips the answer at the boundary:
    on a 60 min window delta 3 is 3 <= 2.8 (False), but against the rounded
    tolerance_min of 2 it would be 3 <= 3 (True).
    """
    dur = sum(int(s.get("duration_min") or 0) for s in plan.get("steps") or [])
    delta = dur - requested_min
    return {
        "actual_min": int(dur),
        "delta_min": int(delta),
        "within_tolerance": abs(delta) <= tol + 1,
    }


def _assemble_plan(plan: dict, ranked: list[dict], slots: dict, lat: float, lon: float,
                   cinema_items: list[dict] | None = None,
                   weather: dict | None = None) -> dict:
    """Hard validation pass over the assembled plan.

    Inserts travel legs, then fits total (stops + travel) to the user's time
    budget within ±10%. It respects each step's fixed/flexible tag: it may only
    stretch/shrink flexible steps (cafe dwell, music session, meal, visit, rest
    filler) or insert/remove a flexible filler step. It NEVER rewrites a fixed
    duration (movie runtime, streaming runtime, walking/travel time). If the
    fixed steps alone already exceed the budget, a step is dropped/swapped and
    the user is told why.
    """
    plan = _remove_llm_travel_steps(plan)
    requested_min = float((slots.get("duration_hours") or 4)) * 60
    if requested_min <= 0 or not plan.get("steps"):
        return plan
    tol = _BUDGET_TOL_FRACTION * requested_min
    notes: list[str] = []

    # Ensure every step (incl. LLM-produced ones) carries a fixed/flexible flag,
    # and pin real movie runtimes + showtime disclaimers from ranked candidates.
    _tag_flexibility(plan)
    _ensure_explicit_movie(plan, list(cinema_items or []) + ranked, slots)
    _normalize_movie_steps(plan, list(cinema_items or []) + ranked, slots)
    plan = _fix_generic_place_names(plan, ranked)
    # Clamp any over-long flexible dwell (LLM-emitted etc.) before travel legs
    # are computed, so the budget loop only ever works with realistic caps.
    _clamp_plan_durations(plan)
    plan = _insert_travel_legs(plan, ranked, lat, lon)

    # Break up back-to-back same-category stops before budget fitting so the
    # loop's duration math starts from a diverse sequence.  The pass keeps each
    # swapped step's duration identical to the original, so the budget totals
    # are nearly unchanged; travel legs are then recomputed to reflect any
    # small coordinate shift.
    plan = _diversify_consecutive_stops(
        plan, ranked, slots, weather or {},
        budget=float(slots.get("budget_inr") or 1000),
        minutes=requested_min,
    )
    plan = _insert_travel_legs(plan, ranked, lat, lon)

    def _duration():
        return int(sum(int(s.get("duration_min") or 0) for s in plan["steps"]))

    def _renumber():
        for n, s in enumerate(plan["steps"]):
            s["order"] = n + 1

    # Section 2 fallback, Open-Meteo row: no live weather means neutral
    # conditions (rainy is None) AND one indoor option must still be in the
    # plan, so a wet evening needs no rebuild. Inserted before the budget loop
    # so it is fitted like any other step (flexible, so it can be shaved).
    # Not added when the planner already emitted an indoor step (the rainy
    # branch of _heuristic_plan) or when the whole plan is indoors anyway.
    weather = weather or {}
    if (
        weather.get("rainy") is None
        and not slots.get("stay_home")
        and not any(s.get("kind") == "indoor" for s in plan["steps"])
    ):
        plan["steps"].append(
            {
                "order": len(plan["steps"]) + 1,
                "kind": "indoor",
                "title": "Covered indoor option (weather unavailable)",
                "duration_min": 45,
                "cost_inr": 0,
                "flexible": True,
                "why": (
                    "Live weather could not be fetched, so this keeps a doable "
                    "indoor plan B in the timeline instead of guessing about rain."
                ),
            }
        )
        _renumber()

    for _ in range(12):
        diff = _duration() - requested_min
        if abs(diff) <= tol:
            break
        if diff < 0:
            shortfall = int(-diff)
            flex = [s for s in plan["steps"] if _is_flexible(s) and s.get("kind") != "travel"]

            # (a) Extend flexible music sessions (listening longer is fine) up to a cap.
            for s in flex:
                if shortfall <= 0:
                    break
                if s.get("kind") == "music":
                    d = int(s.get("duration_min") or 0)
                    inc = min(shortfall, 30, max(0, _DUR_CAPS.get("music", 30) - d))
                    if inc > 0:
                        s["duration_min"] = d + inc
                        shortfall -= inc
            # (b) Extend the longest flexible main stop (cafe / restaurant / place dwell),
            # capped so a single stop never exceeds its realistic dwell time.
            main_flex = [
                s for s in flex
                if s.get("kind") in {"restaurant", "cafe", "food", "place", "indoor"}
            ]
            if shortfall > 0 and main_flex:
                longest = max(main_flex, key=lambda s: int(s.get("duration_min") or 0))
                cap = _DUR_CAPS.get(longest.get("kind"), 120)
                cur = int(longest.get("duration_min") or 0)
                inc = min(shortfall, 30, max(0, cap - cur))
                if inc > 0:
                    longest["duration_min"] = cur + inc
                    shortfall -= inc
            # (c) Prefer a MEANINGFUL flexible step for leftover time: a wind-down
            # music leg, or a second short mood-aligned activity from the pool.
            # A single bare buffer is the last resort (and only when the gap is
            # >= ~5 min and no buffer exists yet).
            if shortfall > 0:
                filler, needs_travel = _best_filler(plan, ranked, shortfall, slots)
                if filler:
                    if filler.get("kind") == "music":
                        # Wind-down music belongs at the very END (after any film/
                        # meal), so its 'after the film' blurb matches its position.
                        plan["steps"].append(filler)
                    else:
                        # Physical second activity: keep it BEFORE the film, since
                        # you visit a spot before sitting down for the movie.
                        movie_pos = next(
                            (i for i, s in enumerate(plan["steps"]) if s.get("kind") == "movie"),
                            None,
                        )
                        if movie_pos is not None:
                            plan["steps"].insert(movie_pos, filler)
                        else:
                            plan["steps"].append(filler)
                    if needs_travel:
                        plan = _insert_travel_legs(plan, ranked, lat, lon)
                        _renumber()
                    shortfall -= int(filler.get("duration_min") or 0)
            # (d) Still short: distribute leftover time across ALL flexible steps,
            # each up to its per-kind cap, so leftover time is spread out instead of
            # ballooning one cafe/place into an unrealistic 3-hour stop.
            if shortfall > 0 and flex:
                for s in sorted(flex, key=lambda x: int(x.get("duration_min") or 0), reverse=True):
                    if shortfall <= 0:
                        break
                    cap = _DUR_CAPS.get(s.get("kind"), 120)
                    cur = int(s.get("duration_min") or 0)
                    inc = min(shortfall, max(0, cap - cur))
                    if inc > 0:
                        s["duration_min"] = cur + inc
                        shortfall -= inc
                if shortfall > 0:
                    # Every real stop is at its realistic cap. Absorb the residual
                    # into extra capped pacing buffers instead of inflating ONE
                    # cafe/place into a multi-hour stop (the cap is an invariant we
                    # never break, even for very long requests).
                    shortfall -= _add_buffer_steps(plan, shortfall)
                shortfall = 0
            _renumber()
        else:
            # Over budget. NEVER shrink a fixed duration (movie runtime / travel /
            # walk). Only flexible steps may be shaved, down to a per-kind floor.
            stops = [i for i, s in enumerate(plan["steps"]) if s.get("kind") in _PHYSICAL_KINDS]
            if not stops:
                break
            kind_min = {"restaurant": 40, "food": 40, "cafe": 40, "place": 20, "indoor": 15}
            shavable = [
                i for i in stops
                if _is_flexible(plan["steps"][i])
            ]
            if shavable:
                idx = max(shavable, key=lambda i: int(plan["steps"][i].get("duration_min") or 0))
                s = plan["steps"][idx]
                cur = int(s.get("duration_min") or 0)
                floor = int(kind_min.get(s.get("kind"), 20))
                s["duration_min"] = max(floor, cur - int(diff - tol))
            elif len(stops) > 1:
                # Every remaining physical stop is fixed (movie runtime + travel)
                # and they ALREADY exceed the budget. Drop the lowest-priority one
                # instead of rewriting a real duration, and tell the user why.
                drop_idx = min(stops, key=lambda i: int(plan["steps"][i].get("duration_min") or 0))
                dropped = plan["steps"][drop_idx]
                notes.append(
                    f"Removed “{dropped.get('title') or dropped.get('kind')}”: the fixed movie "
                    f"runtime plus travel already exceed your {requested_min / 60:g} hr budget "
                    f"({requested_min:.0f} min), and durations like the film's actual runtime can't be "
                    f"shrunk to force a fit."
                )
                plan["steps"].pop(drop_idx)
                plan = _insert_travel_legs(plan, ranked, lat, lon)
            _renumber()

    # Keep at most a single buffer per trip (merge any duplicates/adjacent rests).
    plan = _collapse_rest_buffers(plan)
    plan = _limit_rest_filler(plan)
    dur = sum(int(s.get("duration_min") or 0) for s in plan["steps"])
    cost = sum(int(s.get("cost_inr") or 0) for s in plan["steps"])
    diff = dur - requested_min
    if abs(diff) > tol + 1 and plan["steps"]:
        # Last-resort force-fit: only flexible steps may be adjusted. If none
        # remain and we're still over, drop the smallest fixed stop instead.
        flexible = [s for s in plan["steps"] if _is_flexible(s)]
        if flexible:
            target = max(flexible, key=lambda s: int(s.get("duration_min") or 0))
            target["duration_min"] = max(0, int(target.get("duration_min") or 0) - int(diff))
            dur = sum(int(s.get("duration_min") or 0) for s in plan["steps"])
            diff = dur - requested_min
        elif diff > 0:
            fixed_stops = [i for i, s in enumerate(plan["steps"]) if s.get("kind") in _PHYSICAL_KINDS]
            if fixed_stops:
                drop_idx = max(fixed_stops, key=lambda i: int(plan["steps"][i].get("duration_min") or 0))
                dropped = plan["steps"][drop_idx]
                notes.append(
                    f"Removed “{dropped.get('title') or dropped.get('kind')}” so the plan "
                    f"fits your {requested_min/60:g} hr budget without faking a runtime."
                )
                plan["steps"].pop(drop_idx)
                plan = _insert_travel_legs(plan, ranked, lat, lon)
                dur = sum(int(s.get("duration_min") or 0) for s in plan["steps"])
                diff = dur - requested_min

    plan["budget_notes"] = notes
    plan = _finalize_step_order_and_blurbs(plan)
    dur = sum(int(s.get("duration_min") or 0) for s in plan["steps"])
    cost = sum(int(s.get("cost_inr") or 0) for s in plan["steps"])
    plan["requested_minutes"] = int(requested_min)
    fit = _budget_fit(plan, requested_min, tol)
    plan["budget_fit"] = {
        "requested_min": int(requested_min),
        "actual_min": fit["actual_min"],
        "delta_min": fit["delta_min"],
        "tolerance_min": int(round(tol)),
        "within_tolerance": fit["within_tolerance"],
        "fixed_unchanged": True,
    }
    b = slots.get("budget_inr")
    has_budget = b is not None
    budget: float = float(b or 0)
    plan["budget"] = {
        "budget_inr": int(budget) if has_budget else None,
        "party_size": party_size(slots),
        "total_cost_inr": cost,
        "over_budget": bool(has_budget and cost > budget),
        "excess_inr": int(max(0, cost - budget)) if has_budget else 0,
        "percent_used": round(cost / budget * 100, 1)
        if has_budget and budget > 0
        else (100.0 if has_budget and cost > 0 else (0.0 if has_budget else None)),
    }
    if abs(dur - requested_min) > tol + 1:
        log.warning(
            "budget fit incomplete: %d vs %d (±%.0f) — returning best effort",
            dur, requested_min, tol
        )
    return plan


def _live_source(name: str, label: str, failed: set[str]) -> str:
    """Provenance line for a live lookup — must admit failure.

    Claiming "Overpass/OSM (live)" for a batch that actually raised is the
    same honesty bug `_weather_usage_source` exists to prevent.
    """
    if name in failed:
        return "unavailable (provider error, no data returned)"
    return label


def _weather_usage_source(weather: dict) -> str:
    """Provenance line for the tool_usage panel — must agree with the actual
    fetch result. Claiming "Open-Meteo (live)" when get_weather returned the
    unavailable dict violates the honesty rule (the plan silently degrades to
    not-rainy while the panel claims live data)."""
    if isinstance(weather, dict) and weather.get("source") == "open-meteo":
        return "Open-Meteo (live)"
    return "unavailable (no live weather)"


def run_pipeline(
    message: str,
    user_id: str = "demo",
    lat: float | None = None,
    lon: float | None = None,
    prompt_name: str | None = None,
    location_names: dict | None = None,
) -> dict[str, Any]:
    ensure_user(user_id)
    resolved_meta = location_names if isinstance(location_names, dict) else {}
    lat = lat if lat is not None else settings.default_lat
    lon = lon if lon is not None else settings.default_lon
    used_default_location = resolved_meta.get("source") in {"default", "profile"} or (
        not resolved_meta and lat == settings.default_lat and lon == settings.default_lon
        and not resolved_meta.get("gps_live")
    )
    location = providers.reverse_geocode(lat, lon)
    log.info(
        "resolved location: lat=%.4f lon=%.4f → %s",
        lat, lon, location
    )
    slots = extract_intent(message)
    user_typed_city = (
        resolved_meta.get("source") in {"user", "user-input"}
        and bool((resolved_meta.get("city") or "").strip())
    )
    if user_typed_city:
        city = resolved_meta["city"].strip()
        location = {
            **location,
            "city": city,
            "label": city,
            "source": resolved_meta.get("source") or "user",
        }
        if resolved_meta.get("area"):
            location["area"] = resolved_meta["area"]
        slots["city"] = city
    elif resolved_meta:
        for _k in ("city", "area", "state", "country", "country_code", "display_name"):
            if resolved_meta.get(_k):
                location = {**location, _k: resolved_meta[_k]}
        location["label"] = resolved_meta.get("label") or location.get("label")
        location["source"] = resolved_meta.get("source") or location.get("source")
    decisions: list[dict] = []
    retrieval_path: list[str] = []
    if prompt_name:
        slots["workflow"] = prompt_name
    slots["city"] = (
        location.get("city")
        or (resolved_meta.get("city") if resolved_meta else None)
        or settings.default_city
    )
    if location.get("city"):
        location["label"] = location.get("city")

    # Derive mood/prefs from the already-extracted slots instead of re-running
    # the LLM twice (avoids 2 extra Groq round-trips per request).
    mood = {
        "current_mood": slots.get("current_mood"),
        "desired_mood": slots.get("desired_mood"),
        "mood_intensity": slots.get("mood_intensity"),
        "mood_trajectory": slots.get("mood_trajectory"),
        "emotional_constraints": slots.get("constraints"),
        "agent": slots.get("_agent"),
    }
    prefs = {
        "implicit_preferences": slots.get("implicit_preferences"),
        "budget_inr": slots.get("budget_inr"),
        "party_size": slots.get("party_size"),
        "duration_hours": slots.get("duration_hours"),
        "social": slots.get("social"),
        "intensity": slots.get("intensity"),
    }

    memories = mcp.call(
        "get_user_profile",
        user_id=user_id,
        query=message,
        categories=["preference", "pattern", "feedback", "episodic"],
    )["memories"]
    decisions.append({"diamond": "Does Mem0 contain relevant user memory?", "answer": bool(memories)})
    retrieval_path.append("mem0")
    preferences = _preference_signals(memories)
    decisions.append({
        "diamond": "Are stored preferences usable for biasing?",
        "answer": bool(preferences.get("movie_language") or preferences.get("movie_genres")
                        or preferences.get("music_language") or preferences.get("cuisine")),
    })

    rag_query = " ".join(
        [
            message,
            str(slots.get("desired_mood") or ""),
            "quiet cafe relaxing movie calming music low intensity",
        ]
    )
    rag_hits, rag_conf = knowledge.retrieve(rag_query, k=10)
    rag_ok = rag_conf >= 0.12
    decisions.append({"diamond": "Is RAG retrieval confidence sufficient?", "answer": rag_ok, "confidence": rag_conf})
    retrieval_path.append("rag")

    # Weather is fetched here rather than in the parallel batch: it gates the
    # music seed rotation, and that rotated query is what the "music" task
    # searches with, so weather must be resolved before the batch is submitted.
    # A dead Open-Meteo is reported, never invented: rainy stays unknown.
    provider_errors: list[str] = []
    failed_tools: set[str] = set()
    try:
        weather = mcp.call("get_weather", lat=lat, lon=lon)
    except Exception as exc:
        log.warning("get_weather failed: %s", exc)
        provider_errors.append(f"get_weather: {exc}")
        failed_tools.add("weather")
        weather = {
            "temperature_c": None,
            "rainy": None,
            "condition": "unknown",
            "source": "unavailable",
            "freshness": "unknown",
            "lat": lat,
            "lon": lon,
        }
    decisions.append({"diamond": "Is live API data required?", "answer": True})
    retrieval_path.append("live-api")

    stay_home = bool(slots.get("stay_home"))

    # --- Music language: explicit user mention > stored preference > locale. ----
    # Never treat locale-inferred language as a stored preference — we only
    # bias the playlist when the user actually said a language (explicit) or
    # they later liked a playlist whose language was explicit (stored pref).
    explicit_music_lang = (slots.get("music_language") or "").strip() or None
    lang = explicit_music_lang
    if not lang:
        lang = preferences.get("music_language")
    if not lang:
        lang = nlu.infer_locale_language(
            location.get("city"), location.get("state_label") or location.get("state")
        )
    slots["music_language"] = lang
    slots["music_language_explicit"] = bool(explicit_music_lang)
    slots["music_region"] = (location.get("country_code") or "IN").upper()

    music_q = _derive_search_query(message, slots, "music", preferences)
    movie_q = _derive_search_query(message, slots, "movie", preferences)
    restaurant_mood = (slots.get("desired_mood") or slots.get("current_mood") or "").lower()
    # Rotate the stylistic seed so an identical mood does not produce an
    # identical Spotify result set every single evening.
    music_q = _rotate_music_query(music_q, slots, weather, user_id)

    # --- Run all independent live lookups in parallel to cut latency ---
    # (cafe places, music, books, movies, restaurants, and — if going out — cinemas)
    def _movies():
        lang = preferences.get("movie_language_code")
        if stay_home:
            retrieval_path.append("tmdb-streaming")
            return mcp.call("suggest_movies", query=movie_q, limit=8,
                            watch_at_home=True, language=lang,
                            region=slots.get("music_region") or "IN")
        return mcp.call("suggest_movies", query=movie_q, limit=8,
                        watch_at_home=False, language=lang,
                        region=slots.get("music_region") or "IN")

    def _restaurants():
        retrieval_path.append("osm-restaurants")
        return mcp.call(
            "search_restaurants",
            lat=lat, lon=lon,
            mood=restaurant_mood if restaurant_mood else None,
            limit=8,
        )

    def _cinemas():
        if stay_home:
            return []
        return mcp.call("find_nearby_cinemas", lat=lat, lon=lon)

    tasks = {
        "places": lambda: mcp.call("find_nearby_places", lat=lat, lon=lon, q=None),
        "music": lambda: mcp.call("search_music", query=music_q,
                                  country=slots.get("music_region") or "IN", limit=24),
        "books": lambda: mcp.call("search_books", query="comfort quiet contemporary"),
        "movies": _movies,
        "restaurants": _restaurants,
        "cinemas": _cinemas,
    }

    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        futures = {ex.submit(fn): name for name, fn in tasks.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                results[name] = fut.result()
            except Exception as exc:  # never let one lookup fail the whole plan
                log.warning("parallel lookup %s failed: %s", name, exc)
                provider_errors.append(f"{name}: {exc}")
                failed_tools.add(name)
                results[name] = []

    places = results["places"]
    music = _exclude_recent_tracks(results["music"], user_id)
    books = results["books"]
    streaming_movies = results["movies"] if stay_home else []
    movies = results["movies"]
    restaurants = results["restaurants"]
    cinemas: list[dict] = results["cinemas"] or []
    cinema_items = _movie_candidates(
        cinemas, lat, lon,
        region=slots.get("music_region") or "IN",
        films=None if stay_home else (movies if movies else None),
    )

    if not rag_ok:
        retrieval_path.append("adaptive-fallback")
        # The web fallback is optional enrichment: it must never be the one
        # thing that takes the whole plan down. Failure here is recorded like
        # any other provider failure and the pipeline keeps going with the
        # (thin) RAG hits it already has.
        try:
            snippets = mcp.call(
                "search_web_knowledge",
                query=f"{slots.get('city') or settings.default_city} quiet cafe relaxing evening",
            )
            for snip in (snippets or [])[:3]:
                knowledge.ingest(
                    {
                        "id": snip.get("id"),
                        "title": snip.get("title"),
                        "kind": "web",
                        "text": snip.get("text"),
                        "source": "web-acquisition",
                    }
                )
            rag_hits, rag_conf = knowledge.retrieve(rag_query, k=10)
        except Exception as exc:
            log.warning("adaptive web fallback failed: %s", exc)
            provider_errors.append(f"search_web_knowledge: {exc}")
            failed_tools.add("knowledge")

    seed_walk = {
        "id": "walk:local-street",
        "title": f"20-minute walk along a quiet stretch near {slots.get('city') or 'you'}",
        "kind": "place",
        "subtype": "walk",
        "text": "Low-effort outdoor reset near you, not intense",
        "moods": ["calm", "refreshed"],
        "estimated_cost": 0,
        "duration_min": 20,
        "intensity": "low",
        "outdoor": True,
        "needs_clear_weather": True,
        "lat": lat,
        "lon": lon,
        "review_quality": 7.5,
    }

    # A walk is only honest if it names a real green/open space. Prefer actual
    # Overpass parks; fall back to the generic seed walk ONLY when none exist
    # near the user, so we never present a fabricated place as real.
    real_walks = providers.nearby_walks(lat, lon, limit=4) if not stay_home else []
    if real_walks:
        pool: list[dict] = list(real_walks)
    else:
        pool = [] if stay_home else [seed_walk]
    pool.extend(rag_hits)
    if not stay_home:
        pool.extend(places)
        pool.extend(restaurants)
    pool.extend(cinema_items)
    pool.extend(movies)
    # Don't re-offer a movie we have already suggested to this user. Applied
    # after every movie source is merged so no path can leak a repeat.
    blocked_movies = _excluded_movie_titles(user_id)
    if blocked_movies:
        pool = [
            it for it in pool
            if not (it.get("kind") in {"movie", "streaming"}
                    and _norm_title(it.get("title") or "") in blocked_movies)
        ]
    pool.extend(music)
    pool.extend(books)

    budget = float(slots.get("budget_inr") or 1000)
    minutes = float(slots.get("duration_hours") or 4) * 60
    filtered = []
    for item in pool:
        item = {**item, "distance_km": _distance(item, lat, lon)}
        if hard_filter(item, slots, weather, budget, minutes):
            score = score_item(item, slots, memories, weather, preferences)
            item["final_score"] = _apply_repeat_penalty(item, score, music_q)
            filtered.append(item)

    decisions.append({"diamond": "Are hard constraints satisfied?", "answer": bool(filtered)})
    ranked = rerank(sorted(filtered, key=lambda x: x["final_score"], reverse=True))
    decisions.append({"diamond": "Is the candidate sufficiently compatible?", "answer": bool(ranked)})

    plan_prompt = PLAN_PROMPT.format(
        slots=slots,
        memory=_memory_block(memories),
        weather=weather,
        candidates=ranked[:12],
        shows=cinema_items,
    )
    plan = _plan_with_budget(plan_prompt, ranked, slots, weather)
    if not plan.get("steps"):
        try:
            plan = _heuristic_plan(ranked, slots, weather)
        except Exception as exc:
            log.error("heuristic plan failed: %s", exc, exc_info=True)
            plan = {
                "steps": [],
                "total_cost_inr": 0,
                "total_duration_min": 0,
                "explanation": "Could not build a plan — please try again.",
                "uncertainty": [],
                "_agent": "fallback-empty",
            }
    plan = _assemble_plan(plan, ranked, slots, lat, lon, cinema_items, weather=weather)
    _attach_music_tracks(plan, music)
    mv_note = _movie_request_note(plan, slots)
    if mv_note:
        plan["explanation"] = (plan.get("explanation") or "") + mv_note
    _remember_suggestions(plan)
    _record_shown_items(plan, user_id)

    reviews = []
    for item in ranked[:4]:
        if item.get("kind") in {"movie", "place"}:
            reviews.append(mcp.analyze_reviews(item.get("title") or "", item.get("text") or ""))

    bundle = {
        "slots": slots,
        "mood": mood,
        "prefs": prefs,
        "mem0": memories,
        "preferences": preferences,
        "rag_confidence": rag_conf,
        "weather": weather,
        "location": {
            **location,
            "gps_live": not used_default_location,
            "label": f"{slots.get('city') or location.get('area') or 'Your area'}, {location.get('city') or settings.default_city}",
            "state_label": location.get("state") or "",
        },
        "ranked": ranked[:12],
        "plan": plan,
        "reviews": reviews,
        "showtimes": cinema_items,
        "restaurants": restaurants,
        "streaming_movies": streaming_movies if stay_home else [],
        "stay_home": stay_home,
        "music_query": music_q,
        "tool_usage": {
            "weather": {
                "tool": "get_weather",
                "source": _weather_usage_source(weather),
            },
            "places": {
                "tool": "find_nearby_places",
                "source": _live_source(
                    "places", "Overpass/OSM (live, around your location)", failed_tools
                ),
            },
            "restaurants": {
                "tool": "search_restaurants" + (" (by mood)" if restaurant_mood else ""),
                "source": _live_source("restaurants", "Overpass/OSM (live)", failed_tools),
            },
            "cinemas": {
                "tool": "find_nearby_cinemas",
                "source": _live_source("cinemas", "Overpass/OSM (live)", failed_tools),
            },
            "movies": {"tool": "search_home_movies" if stay_home else "search_movies", "source": ("TMDB movie titles on real map cinemas; runtime from TMDB when available, runtime/showtime marked 'estimate' otherwise" if not stay_home else "streaming search")},
            "music": {"tool": "search_music",
                      "source": _live_source("music", "Spotify (live, no fallback)", failed_tools)},
            "books": {"tool": "search_books", "source": _live_source("books", "book search", failed_tools)},
            "knowledge": {"tool": "retrieve_knowledge" if rag_ok else "search_web_knowledge",
                          "source": _live_source("knowledge", "RAG / web knowledge", failed_tools)},
            "memory": {"tool": "get_user_profile", "source": "Mem0"},
        },
        "decisions": decisions,
        "retrieval_path": retrieval_path,
        "provider_errors": provider_errors,
        "agents": {
            "extract": slots.get("_agent"),
            "extract_model": slots.get("_model"),
            "plan": plan.get("_agent") or plan.get("_model"),
            "groq_ready": router.groq_ready,
            "gemini_ready": router.gemini_ready,
        },
        "mcp": {
            "tools": list(mcp.tools),
            "prompts": mcp.prompts,
            "note": "MCP is the AI-facing interface. TMDB/iTunes/OSM/Open-Meteo are providers.",
        },
        "action": {
            "available": not stay_home,
            "requires_confirmation": True,
            "prepare": "prepare_movie_booking" if not stay_home else None,
            "confirm": "confirm_movie_booking" if not stay_home else None,
        },
        "journal_insight": journal.insight(user_id),
    }
    event_id = save_event(user_id, message, {"plan": plan, "slots": slots})
    bundle["event_id"] = event_id
    journal.log_mood_entry(user_id, slots, weather, plan, event_id=event_id)
    try:
        from moodos.memory_writer import remember_plan_outcome

        bundle["memory_write"] = remember_plan_outcome(
            user_id, message, slots, plan, outcome="generated", event_id=event_id
        )
    except Exception as exc:
        log.warning("memory write skipped: %s", exc)
    return bundle
