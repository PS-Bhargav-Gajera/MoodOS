"""Deterministic mood normalization + time derivation for the mood journal.

The journal is statistical, not semantic: to average and trend free-text moods
("exhausted", "de-stressed", "happy"...) we map them onto a canonical -1..+1
valence with a small ordered lexicon. No LLM, no randomness — same input always
yields the same number.

This module is intentionally dependency-free so it can be unit-tested in isolation.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

# Ordered by extremity. First phrase that matches wins, so more intense words
# are checked before milder ones. Matching is whole-word/phrase (see _has).
_VALENCE_TABLE: list[tuple[float, tuple[str, ...]]] = [
    (-1.0, (
        "stressed", "stress", "stressful", "anxious", "anxiety", "angry", "furious",
        "sad", "depressed", "depressing", "overwhelmed", "overwhelming", "panicked",
        "panic", "tense", "miserable", "awful", "terrible", "horrible", "upset",
    )),
    (-0.6, (
        "exhausted", "exhausting", "exhaust", "tired", "fatigued", "drained",
        "burned out", "burnt out", "worn out", "sleepy", "spent", "wearied",
    )),
    (-0.3, (
        "bored", "boring", "restless", "unmotivated", "meh", "blah", "low energy",
        "low", "down", "lazy", "sluggish", "uneasy",
    )),
    (0.0, ("neutral", "okay", "ok", "fine", "normal", "alright", "so-so", "unsure")),
    (0.5, (
        "calm", "relaxed", "relax", "peaceful", "content", "comfortable", "cozy",
        "quiet", "unwind", "serene", "chill", "grounded", "soothed",
    )),
    (0.8, ("happy", "refreshed", "cheerful", "good", "pleasant", "glad", "delighted", "upbeat")),
    (1.0, (
        "energized", "energetic", "excited", "exciting", "thrilled", "celebrating",
        "celebrate", "great", "amazing", "fantastic", "ecstatic", "elated", "pumped",
    )),
]

# Phrases that contain a negative word but mean the opposite. Checked first.
_POSITIVE_OVERRIDES = (
    ("de-stressed", 0.6), ("destressed", 0.6), ("de stressed", 0.6),
    ("unstressed", 0.6),
)

_WORD_RE_CACHE: dict[str, re.Pattern] = {}


def _has(text: str, phrase: str) -> bool:
    pat = _WORD_RE_CACHE.get(phrase)
    if pat is None:
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])")
        _WORD_RE_CACHE[phrase] = pat
    return bool(pat.search(text))


def mood_valence(mood: str | None) -> float:
    """Map a free-text mood onto -1.0 .. +1.0. Unknown/empty -> 0.0."""
    if not mood:
        return 0.0
    text = str(mood).lower().strip()
    for phrase, value in _POSITIVE_OVERRIDES:
        if _has(text, phrase):
            return value
    for value, phrases in _VALENCE_TABLE:
        for phrase in phrases:
            if _has(text, phrase):
                return value
    return 0.0


def intensity_score(intensity: str | None) -> int:
    """low|medium|high -> 1|2|3 (default medium)."""
    return {"low": 1, "medium": 2, "high": 3}.get(str(intensity or "").lower(), 2)


def time_bucket(hour: int) -> str:
    """Coarse part of day for the local hour."""
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def local_now(now: datetime | None = None) -> datetime:
    """Local wall-clock time (assumes the server runs in the user's timezone,
    which holds for this local-first app; falls back to UTC elsewhere)."""
    if now is not None:
        return now
    return datetime.now().astimezone()


def derive_time_fields(now: datetime | None = None) -> dict:
    """Local date / weekday / hour / bucket for a journal entry.

    Pass `now` (an aware datetime) to backdate an entry — used by tests.
    """
    dt = local_now(now)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return {
        "created_at": dt.astimezone(timezone.utc).isoformat(),
        "local_date": dt.strftime("%Y-%m-%d"),
        "day_of_week": dt.weekday(),  # Monday = 0 .. Sunday = 6
        "hour_local": dt.hour,
        "time_bucket": time_bucket(dt.hour),
    }


def dominant_plan_kind(plan: dict | None) -> str | None:
    """Most common non-travel activity type; 'mixed' when there's no majority."""
    plan = plan or {}
    kinds: list[str] = []
    for step in plan.get("steps") or []:
        kind = step.get("kind")
        if kind and kind != "travel":
            kinds.append(str(kind))
    if not kinds:
        return None
    counts: dict[str, int] = {}
    for kind in kinds:
        counts[kind] = counts.get(kind, 0) + 1
    top = max(counts.values())
    winners = [k for k, c in counts.items() if c == top]
    if len(winners) == 1:
        return winners[0]
    return "mixed"


def plan_summary(plan: dict | None, limit: int = 3) -> str | None:
    """Short 'A → B → C' description of the chosen steps."""
    plan = plan or {}
    titles = [
        str(s.get("title") or s.get("kind") or "").strip()
        for s in plan.get("steps") or []
        if s.get("kind") != "travel"
    ]
    titles = [t for t in titles if t]
    if not titles:
        return None
    return " → ".join(titles[:limit])