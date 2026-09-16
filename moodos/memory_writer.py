"""Memory write path: durable, deduplicated, guarded.

What may be written, by category:

  preference — a taste the user states or reinforces (cuisine, music language,
               movie language/genre, movie-going, cafe venues, social style,
               budget band). Only written when it's an explicit signal, never
               inferred from a passing current-mood mention or from locale
               (liking a playlist while in Jaipur is NOT learning "Hindi music"
               unless the user named a language).
  pattern    — recurring behaviour: low-energy after college, prefers staying
               home, rainy-day habits. Needs a repeated or self-described
               tendency, not a single transient state.
  episodic   — "this specific outing happened / was enjoyed / was skipped". A
               record, never promoted to a standing rule.
  feedback   — explicit rating language from the feedback flow.

Guardrails enforced here:
  * transient session words ("tonight", "today", "right now") block a write —
    a one-off mood is not a preference.
  * every write is search-before-write deduplicated within its category; a
    near-duplicate is REINFORCED (confidence + reinforced stamp) instead of
    duplicated, so repeated happy reactions strengthen one memory.
  * nothing in this module may raise: memory is a soft feature, the plan API
    must not fail because of it.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from moodos.memory import mem0

log = logging.getLogger("moodos.memory_writer")

# One-off phrasing that must never be persisted as a durable fact.
_TRANSIENT_WORDS = ("tonight", "today", "right now", "this evening", "just now", "at the moment")

# TMDB 2-letter language codes -> readable names, used to phrase movie-language
# preference memories and to map them back at read time.
_LANGUAGE_NAMES = {
    "hi": "Hindi", "en": "English", "ta": "Tamil", "te": "Telugu", "kn": "Kannada",
    "ml": "Malayalam", "mr": "Marathi", "bn": "Bengali", "pa": "Punjabi",
    "gu": "Gujarati", "bho": "Bhojpuri", "or": "Odia", "as": "Assamese", "ur": "Urdu",
}
_LANGUAGE_CODES = {v.lower(): k for k, v in _LANGUAGE_NAMES.items()}

# Explicit signals we are willing to persist from a single utterance.
_SOCIAL_SIGNALS = {"solo", "friends", "family", "date"}
_MUSIC_KINDS = ("song", "songs", "music", "playlist", "listen", "listening", "listen to", "gaana")


def _find_duplicate(user_id: str, text: str, category: str) -> dict | None:
    """Search-before-write: the most similar existing memory under this
    category, or None. A token-overlap near-duplicate is a match."""
    hits = mem0.retrieve(user_id, text, k=3, categories=[category])
    for hit in hits:
        existing = str(hit.get("text") or "").strip().lower()
        if not existing:
            continue
        if existing == text.strip().lower():
            return hit
        a = set(text.lower().split())
        b = set(existing.split())
        if not a or not b:
            continue
        overlap = len(a & b) / max(len(a), len(b))
        if overlap >= 0.75:
            return hit
        if len(a & b) >= 3 and overlap >= 0.6:
            return hit
    return None


def _is_candidate_phrase_duplicate(user_id: str, text: str, category: str) -> bool:
    """Search-before-write: is this fact already remembered under this category?"""
    return _find_duplicate(user_id, text, category) is not None


def _reinforce_memory(user_id: str, existing: dict, fact: dict) -> None:
    """Bump a matched memory instead of duplicating it: raise its confidence a
    little and stamp 'reinforced'. Never raises."""
    memory_id = existing.get("id")
    meta = dict(existing.get("metadata") or {})
    meta["reinforced_count"] = int(meta.get("reinforced_count") or 0) + 1
    meta["last_reinforced"] = datetime.now(timezone.utc).isoformat()
    meta.setdefault("category", fact.get("category") or "preference")
    if memory_id:
        try:
            mem0.update(user_id, memory_id, metadata=meta)
        except Exception as exc:
            log.warning("memory reinforce (update) failed: %s", exc)
        try:
            mem0.local.update(
                user_id,
                memory_id,
                metadata=meta,
                confidence=min(0.95, float(existing.get("confidence") or 0.6) + 0.08),
            )
        except Exception as exc:
            log.warning("memory reinforce (local) failed: %s", exc)


def _upsert(user_id: str, fact: dict, source: str, session_id: str | None = None) -> dict:
    """Write one candidate fact if it passes the guardrails. Never raises."""
    try:
        text = (fact.get("text") or "").strip()
        category = fact.get("category") or "preference"
        if not text or len(text) < 8:
            return {"action": "skip-short", "category": category}
        low = text.lower()
        if any(w in low for w in _TRANSIENT_WORDS):
            return {"action": "skip-transient", "category": category}
        dup = _find_duplicate(user_id, text, category)
        if dup:
            _reinforce_memory(user_id, dup, fact)
            return {"action": "dup", "category": category, "reinforced": True}
        metadata = dict(fact.get("metadata") or {})
        if session_id:
            metadata["session_id"] = session_id
        metadata["category"] = category
        category_kind = metadata.get("kind", "")
        kind = "long_term" if category in {"preference", "pattern", "feedback"} else "contextual"
        is_new = mem0.add(
            user_id,
            text,
            kind=kind,
            confidence=float(fact.get("confidence") or 0.6),
            category=category,
            metadata=metadata,
            source=source,
        )
        return {"action": "add" if is_new else "dup", "category": category}
    except Exception as exc:
        log.warning("memory write failed: %s", exc)
        return {"action": "error", "category": category}


def extract_durable_facts(message: str | None, slots: dict | None) -> list[dict]:
    """Explicit durable signals the user stated in this utterance (not guesses)."""
    slots = slots or {}
    facts: list[dict] = []
    message = message or ""

    budget = slots.get("budget_inr")
    if isinstance(budget, (int, float)) and budget > 0:
        band = "budget" if budget < 800 else ("mid" if budget < 2000 else "premium")
        facts.append({
            "text": f"Comfortable spending around ₹{int(budget)} on an evening out ({band} band)",
            "category": "preference",
            "kind": "budget",
            "confidence": 0.6,
            "metadata": {"kind": "budget", "band": band},
        })

    social = slots.get("social")
    if social in _SOCIAL_SIGNALS:
        facts.append({
            "text": f"Often goes out {social}",
            "category": "preference",
            "kind": "social",
            "confidence": 0.6,
            "metadata": {"kind": "social"},
        })

    if slots.get("want_movie"):
        facts.append({
            "text": "Enjoys going to the movies",
            "category": "preference",
            "kind": "activity",
            "confidence": 0.65,
            "metadata": {"kind": "activity"},
        })

    if slots.get("food_priority"):
        facts.append({
            "text": "Treats a good meal as the centerpiece of an outing",
            "category": "preference",
            "kind": "food",
            "confidence": 0.6,
            "metadata": {"kind": "food"},
        })

    if slots.get("stay_home"):
        facts.append({
            "text": "Often prefers staying home over going out",
            "category": "pattern",
            "kind": "lifestyle",
            "confidence": 0.5,
            "metadata": {"kind": "lifestyle"},
        })

    intensity = (slots.get("intensity") or "").lower()
    current = (slots.get("current_mood") or "").lower()
    if intensity == "low" and any(w in current for w in ("exhaust", "tired", "drained", "burnt")):
        facts.append({
            "text": "Prefers low-intensity, low-effort outings when feeling drained",
            "category": "pattern",
            "kind": "intensity",
            "confidence": 0.55,
            "metadata": {"kind": "intensity"},
        })

    from moodos.nlu import detect_music_language

    lang = slots.get("music_language") or detect_music_language(message)
    if lang and any(w in message.lower() for w in _MUSIC_KINDS):
        facts.append({
            "text": f"Enjoys {lang} music",
            "category": "preference",
            "kind": "music",
            "confidence": 0.7,
            "metadata": {"kind": "music", "language": lang},
        })

    return facts


def _episodic_summary(plan: dict | None, liked: bool | None = None) -> str | None:
    plan = plan or {}
    steps = [s for s in plan.get("steps") or [] if s.get("kind") != "travel"]
    if not steps:
        return None
    titles = [str(s.get("title") or s.get("kind") or "").strip() for s in steps[:3]]
    titles = [t for t in titles if t]
    if not titles:
        return None
    head = "Enjoyed" if liked else ("Did not enjoy" if liked is False else "Went for")
    return f"{head}: {' → '.join(titles)}"


def remember_plan_outcome(user_id: str, message: str | None = None, slots: dict | None = None,
                          plan: dict | None = None, outcome: str = "generated",
                          event_id: int | None = None, session_id: str | None = None) -> dict:
    """Write durable memory after a plan is generated, accepted, or rejected.

    outcome: 'generated' | 'accepted' | 'rejected' | 'liked' | 'disliked'
    Returns a small report; never raises.
    """
    session_id = session_id or (f"evt-{event_id}" if event_id else None)
    report: dict[str, Any] = {"outcome": outcome, "written": []}

    try:
        if outcome in {"generated", "accepted", "rejected", "liked", "disliked"}:
            for fact in extract_durable_facts(message, slots):
                result = _upsert(user_id, fact, source="plan", session_id=session_id)
                report["written"].append(result)
    except Exception as exc:
        log.warning("remember_plan_outcome (facts) failed: %s", exc)

    try:
        liked = None
        if outcome in {"accepted", "liked"}:
            liked = True
        elif outcome in {"rejected", "disliked"}:
            liked = False
        summary = _episodic_summary(plan, liked)
        if summary:
            result = _upsert(
                user_id,
                {
                    "text": summary,
                    "category": "episodic",
                    "kind": "plan_summary",
                    "confidence": 0.7,
                    "metadata": {"kind": "plan_summary", "outcome": outcome},
                },
                source="plan",
                session_id=session_id,
            )
            report["written"].append(result)
    except Exception as exc:
        log.warning("remember_plan_outcome (episodic) failed: %s", exc)

    return report


# --- reaction-driven learning -----------------------------------------------

_CUISINE_PAT = re.compile(r"enjoys ([\w\- ]+) food", re.I)


def _parse_cuisine_from_title(title: str | None) -> str | None:
    """Extract a cuisine token from a restaurant title like
    'Main Dish (Italian, Pizza)' -> 'italian'."""
    m = re.search(r"\(([^)]+)\)", title or "")
    if m:
        return m.group(1).split(",")[0].strip().lower() or None
    return None


def extract_reaction_facts(plan: dict | None, slots: dict | None) -> list[dict]:
    """Learn durable, explicit tastes from a HAPPILY-rated plan.

    Only clearly-present attributes become memories:
      * movie/streaming language (from TMDB metadata carried on the step)
      * verified movie genre (mood_fit_verified, real TMDB genres)
      * music language only when the USER explicitly named one (not locale-
        inferred — liking a playlist in Jaipur must not teach "Hindi music")
      * restaurant cuisine
      * cafe/quiet-cafe venue type

    social/stay_home/budget are already written by extract_durable_facts at
    plan-generation time, so we skip them here to avoid double-writing and
    instead REINFORCE them via the dedup path when they match.
    """
    slots = slots or {}
    plan = plan or {}
    facts: list[dict] = []
    explicit_music = bool(slots.get("music_language_explicit")) and bool(slots.get("music_language"))
    try:
        for step in plan.get("steps") or []:
            kind = (step.get("kind") or "").lower()

            # --- movie / streaming: language + top genre -----------------------
            if kind in {"movie", "streaming"}:
                code = str(step.get("original_language") or "").strip().lower()
                name = _LANGUAGE_NAMES.get(code)
                if name:
                    facts.append({
                        "text": f"Prefers {name}-language movies",
                        "category": "preference",
                        "kind": "movie_language",
                        "confidence": 0.75,
                        "metadata": {"kind": "movie_language", "language": code,
                                     "language_name": name},
                    })
                if step.get("mood_fit_verified"):
                    genre = next((g for g in (step.get("genres") or []) if g), None)
                    if genre:
                        facts.append({
                            "text": f"Enjoys {genre} movies",
                            "category": "preference",
                            "kind": "movie_genre",
                            "confidence": 0.7,
                            "metadata": {"kind": "movie_genre", "genre": genre},
                        })

            # --- music: ONLY explicit user language, never locale ----------------
            elif kind == "music" and explicit_music:
                lang = str(slots.get("music_language") or "").strip().capitalize()
                if lang:
                    facts.append({
                        "text": f"Enjoys {lang} music",
                        "category": "preference",
                        "kind": "music",
                        "confidence": 0.7,
                        "metadata": {"kind": "music",
                                     "language": str(slots.get("music_language")).lower()},
                    })

            # --- restaurant: cuisine from step or title -------------------------
            elif kind == "restaurant":
                cuisine = (step.get("cuisine") or "").strip().lower()
                if not cuisine:
                    cuisine = _parse_cuisine_from_title(step.get("title"))
                if cuisine:
                    facts.append({
                        "text": f"Enjoys {cuisine} food",
                        "category": "preference",
                        "kind": "cuisine",
                        "confidence": 0.72,
                        "metadata": {"kind": "cuisine", "cuisine": cuisine},
                    })

            # --- cafe / quiet cafe venue (reinforces bootstrap seed) ------------
            elif kind in {"cafe", "place"}:
                title_low = str(step.get("title") or "").lower()
                if kind == "cafe" or any(w in title_low for w in ("cafe", "coffee", "tea")):
                    facts.append({
                        "text": "Likes quiet cafes",
                        "category": "preference",
                        "kind": "venue",
                        "confidence": 0.75,
                        "metadata": {"kind": "venue", "venue_type": "cafe"},
                    })
    except Exception as exc:
        log.warning("extract_reaction_facts failed: %s", exc)
    return facts


def learn_from_reaction(
    user_id: str,
    plan: dict | None,
    slots: dict | None = None,
    event_id: int | None = None,
    entry_id: int | None = None,
) -> dict:
    """Write preference memories after a user reacts with a happy reaction to a
    plan step in the journal strip.  Returns a small report; never raises."""
    session_id = (
        f"reaction-evt-{event_id}" if event_id
        else (f"reaction-entry-{entry_id}" if entry_id else None)
    )
    report: dict[str, Any] = {"learned": 0, "written": []}
    try:
        for fact in extract_reaction_facts(plan, slots):
            result = _upsert(user_id, fact, source="reaction", session_id=session_id)
            report["written"].append(result)
            if result.get("action") == "add":
                report["learned"] += 1
    except Exception as exc:
        log.warning("learn_from_reaction failed: %s", exc)
    return report