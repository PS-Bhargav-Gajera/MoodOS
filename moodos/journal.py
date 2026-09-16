"""Mood journal: capture + rule-based trend aggregation.

Design notes
------------
* Storage lives in SQLite (see moodos.db.mood_entries) — this is time-series
  data we GROUP BY, deliberately NOT semantic Mem0 memory.
* Everything here is deterministic and LLM-free: a plan request writes one row
  (cheap, local), and the reads are simple grouping/averaging.
* `insight()` is a tiny rule engine over the aggregates so the plan flow can
  surface one human sentence without any extra model call.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from moodos import db
from moodos.mood_map import (
    derive_time_fields,
    dominant_plan_kind,
    intensity_score,
    mood_valence,
    plan_summary,
)

log = logging.getLogger("moodos.journal")

MIN_ENTRIES_FOR_INSIGHT = 5
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


# --- write path -------------------------------------------------------------

def log_mood_entry(user_id: str, slots: dict | None = None, weather: dict | None = None,
                   plan: dict | None = None, event_id: int | None = None,
                   source: str = "plan", now: datetime | None = None) -> int | None:
    """Record one journal entry for a generated plan. Never raises."""
    try:
        slots = slots or {}
        weather = weather or {}
        row = {
            **derive_time_fields(now),
            "user_id": user_id,
            "event_id": event_id,
            "current_mood": slots.get("current_mood"),
            "mood_valence": mood_valence(slots.get("current_mood")),
            "desired_mood": slots.get("desired_mood"),
            "desired_valence": mood_valence(slots.get("desired_mood")) if slots.get("desired_mood") else None,
            "mood_intensity": slots.get("intensity"),
            "intensity_score": intensity_score(slots.get("intensity")),
            "social": slots.get("social"),
            "budget_inr": slots.get("budget_inr"),
            "duration_hours": slots.get("duration_hours"),
            "weather_condition": weather.get("condition"),
            "weather_rainy": 1 if weather.get("rainy") else 0,
            "temperature_c": weather.get("temperature_c"),
            "plan_kind": dominant_plan_kind(plan),
            "plan_summary": plan_summary(plan),
            "stay_home": 1 if slots.get("stay_home") else 0,
            "source": source,
        }
        return db.insert_mood_entry(row)
    except Exception as exc:
        log.warning("journal write failed: %s", exc)
        return None


def recent_entries(user_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
    return db.list_mood_entries(user_id, limit=limit, offset=offset)


def delete_entry(user_id: str, entry_id: int) -> bool:
    return db.delete_mood_entry(user_id, entry_id)


def clear_journal(user_id: str) -> int:
    return db.delete_mood_entries(user_id)


REACTION_LABELS = ("happy", "neutral", "sad")
_REACTION_VALENCE = {"happy": 1.0, "neutral": 0.0, "sad": -1.0}


def react_to_entry(user_id: str, entry_id: int, reaction: str) -> bool:
    """Record a 3-way reaction (happy/neutral/sad) on one journal entry."""
    if reaction not in REACTION_LABELS:
        raise ValueError(f"reaction must be one of {REACTION_LABELS}")
    return db.update_mood_reaction(user_id, entry_id, reaction) if is_reactable_entry(user_id, entry_id) else False


def is_reactable_entry(user_id: str, entry_id: int) -> bool:
    """An entry can be reacted to at most once — the first reaction wins."""
    if not entry_id:
        return False
    reactions = db.get_entry_reactions(user_id, [entry_id])
    return entry_id in reactions and reactions[entry_id] is None


def _summary_for(entry: dict) -> dict:
    """Trim an entry row to exactly what the strip needs; adds a human line."""
    parts = []
    mood = entry.get("current_mood")
    if mood:
        parts.append(mood)
    place = entry.get("plan_summary") or entry.get("plan_kind")
    if place:
        parts.append(place)
    return {
        "id": entry.get("id"),
        "local_date": entry.get("local_date"),
        "time_bucket": entry.get("time_bucket"),
        "mood_valence": entry.get("mood_valence"),
        "plan_kind": entry.get("plan_kind"),
        "plan_summary": entry.get("plan_summary"),
        "mood_reaction": entry.get("mood_reaction"),
        "reactable": entry.get("mood_reaction") is None,
        "line": " · ".join(parts) if parts else "Plan entry",
    }


def summary_strip(user_id: str, limit: int = 12) -> dict:
    """Recent entries condensed for the strip + how many are already rated."""
    entries = db.list_mood_entries(user_id, limit=limit)
    items = [_summary_for(e) for e in entries]
    rated = sum(1 for it in items if not it["reactable"])
    return {"entries": items, "rated_count": rated, "total_shown": len(items)}


MIN_REACTIONS_FOR_INSIGHT = 3


def _reaction_pattern(entries: list[dict]) -> dict | None:
    """Reaction insight: how well recent plans are landing, per the ratings.

    Reaction values: happy=+1, neutral=0, sad=-1. A strong average tells us
    plans are landing (or missing). A "sad/neutral despite a good mood" combo
    flags a plan/delivery mismatch rather than a bad day.
    """
    reacted = [e for e in entries if e.get("mood_reaction")]
    if len(reacted) < MIN_REACTIONS_FOR_INSIGHT:
        return None

    avg = _avg([_REACTION_VALENCE[str(e["mood_reaction"])] for e in reacted])
    sample = len(reacted)

    if avg is not None and avg <= -0.5:
        return {
            "kind": "plans_missing",
            "text": "Some of your recent plans missed the mark at rating time — I'll aim for something lighter and closer to your taste.",
            "sample_size": sample,
        }

    if avg is not None and avg >= 0.5:
        return {
            "kind": "plans_landing",
            "text": "Your recent plans are landing well — I'll keep walking the same route for your next evenings.",
            "sample_size": sample,
        }

    mismatches = [
        e for e in reacted
        if e["mood_reaction"] == "sad" and (e.get("mood_valence") or 0) >= 0.3
    ]
    if len(mismatches) >= 2:
        return {
            "kind": "reaction_mismatch",
            "text": "Even on days you felt fine, a few plans fell flat — let me rethink how I build those evenings.",
            "sample_size": sample,
        }

    return None


# --- helpers ----------------------------------------------------------------

def _avg(numbers: list[float]) -> float | None:
    clean = [float(n) for n in numbers if n is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 3)


def _top(values: list[str | None]) -> str | None:
    clean = [str(v) for v in values if v]
    if not clean:
        return None
    return Counter(clean).most_common(1)[0][0]


def _entry_dt(entry: dict) -> datetime:
    raw = entry.get("created_at") or ""
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _week_key(local_date: str) -> str:
    try:
        iso = datetime.strptime(local_date, "%Y-%m-%d").isocalendar()
    except (ValueError, TypeError):
        return "unknown"
    return f"{iso[0]}-W{iso[1]:02d}"


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return round(cov / (vx ** 0.5 * vy ** 0.5), 3)


# --- aggregations -----------------------------------------------------------

def weekly_trend(user_id: str, weeks: int = 4) -> list[dict]:
    """Avg mood valence per ISO week, oldest first, limited to the last N weeks."""
    entries = db.all_mood_entries(user_id)
    buckets: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        buckets[_week_key(entry.get("local_date") or "")].append(entry)
    rows = []
    for key in sorted(k for k in buckets if k != "unknown"):
        group = buckets[key]
        rows.append({
            "week": key,
            "count": len(group),
            "avg_valence": _avg([g.get("mood_valence") for g in group]),
            "avg_intensity": _avg([g.get("intensity_score") for g in group]),
            "top_mood": _top([g.get("current_mood") for g in group]),
        })
    return rows[-max(weeks, 1):]


def by_weekday(user_id: str) -> list[dict]:
    """One row per Monday..Sunday with average valence and the common mood."""
    entries = db.all_mood_entries(user_id)
    buckets: dict[int, list[dict]] = defaultdict(list)
    for entry in entries:
        dow = entry.get("day_of_week")
        if dow is None:
            continue
        buckets[int(dow)].append(entry)
    rows = []
    for dow in range(7):
        group = buckets.get(dow, [])
        rows.append({
            "day_of_week": dow,
            "day": _WEEKDAYS[dow],
            "count": len(group),
            "avg_valence": _avg([g.get("mood_valence") for g in group]),
            "avg_intensity": _avg([g.get("intensity_score") for g in group]),
            "top_mood": _top([g.get("current_mood") for g in group]),
        })
    return rows


def by_time_of_day(user_id: str) -> list[dict]:
    """Mood by coarse part of day."""
    entries = db.all_mood_entries(user_id)
    order = ("morning", "afternoon", "evening", "night")
    buckets: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        buckets[str(entry.get("time_bucket") or "unknown")].append(entry)
    rows = []
    for name in order:
        group = buckets.get(name, [])
        rows.append({
            "bucket": name,
            "count": len(group),
            "avg_valence": _avg([g.get("mood_valence") for g in group]),
            "avg_intensity": _avg([g.get("intensity_score") for g in group]),
            "top_mood": _top([g.get("current_mood") for g in group]),
        })
    return rows


def weather_correlation(user_id: str) -> dict:
    """Mood split by rain vs clear, by temperature band, and mood~temp Pearson r."""
    entries = db.all_mood_entries(user_id)
    rainy = [e for e in entries if e.get("weather_rainy")]
    clear = [e for e in entries if not e.get("weather_rainy")]

    def band(temp: float | None) -> str | None:
        if temp is None:
            return None
        if temp < 15:
            return "<15°C"
        if temp < 25:
            return "15-25°C"
        if temp < 32:
            return "25-32°C"
        return ">32°C"

    temp_buckets: dict[str, list[float]] = defaultdict(list)
    temps: list[float] = []
    vals: list[float] = []
    for entry in entries:
        temp = entry.get("temperature_c")
        valence = entry.get("mood_valence")
        name = band(temp)
        if name is not None and valence is not None:
            temp_buckets[name].append(float(valence))
        if temp is not None and valence is not None:
            temps.append(float(temp))
            vals.append(float(valence))

    by_temp = [
        {"band": name, "count": len(values), "avg_valence": _avg(values)}
        for name, values in sorted(temp_buckets.items())
    ]
    return {
        "rainy": {"count": len(rainy), "avg_valence": _avg([e.get("mood_valence") for e in rainy])},
        "clear": {"count": len(clear), "avg_valence": _avg([e.get("mood_valence") for e in clear])},
        "by_temperature": by_temp,
        "temp_valence_r": _pearson(temps, vals),
    }


def calendar_heatmap(user_id: str, weeks: int = 12) -> dict:
    """Per-day cells (GitHub-style) for the last N weeks."""
    weeks = max(1, min(int(weeks or 12), 52))
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=weeks * 7 - 1)
    entries = db.all_mood_entries(user_id)
    by_date: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        local_date = str(entry.get("local_date") or "")
        if not local_date:
            continue
        by_date[local_date].append(entry)
    days = []
    for local_date, group in by_date.items():
        try:
            day = datetime.strptime(local_date, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day < start or day > end:
            continue
        days.append({
            "date": local_date,
            "count": len(group),
            "avg_valence": _avg([g.get("mood_valence") for g in group]),
        })
    days.sort(key=lambda d: d["date"])
    return {"start": start.isoformat(), "end": end.isoformat(), "weeks": weeks, "days": days}


def trends(user_id: str, weeks: int = 4) -> dict:
    """Everything the Journal UI needs in one payload."""
    entries = db.all_mood_entries(user_id)
    total = len(entries)
    return {
        "user_id": user_id,
        "total_entries": total,
        "weeks": weeks,
        "weekly": weekly_trend(user_id, weeks=weeks),
        "by_weekday": by_weekday(user_id),
        "by_time_of_day": by_time_of_day(user_id),
        "weather": weather_correlation(user_id),
        "heatmap": calendar_heatmap(user_id, weeks=max(weeks, 12)),
        "insight": insight(user_id),
    }


# --- insight (rule-based) ---------------------------------------------------

def _avg_since(entries: list[dict], start: datetime, end: datetime, field: str) -> tuple[float | None, int]:
    values = []
    for entry in entries:
        dt = _entry_dt(entry)
        if start <= dt < end and entry.get(field) is not None:
            values.append(float(entry[field]))
    avg = _avg(values)
    return avg, len(values)


def insight(user_id: str) -> dict | None:
    """One deterministic, human sentence — or None when there isn't enough data."""
    entries = db.all_mood_entries(user_id)
    if len(entries) < MIN_ENTRIES_FOR_INSIGHT:
        return None

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=35)

    week_valence, week_n = _avg_since(entries, week_ago, now, "mood_valence")
    base_valence, base_n = _avg_since(entries, month_ago, week_ago, "mood_valence")
    week_intensity, _ = _avg_since(entries, week_ago, now, "intensity_score")
    base_intensity, _ = _avg_since(entries, month_ago, week_ago, "intensity_score")

    # 1) Low energy this week vs the trailing baseline.
    if (week_n >= 2 and base_intensity is not None and week_intensity is not None
            and week_intensity <= base_intensity - 0.3 and week_intensity <= 1.7):
        return {
            "kind": "low_energy",
            "text": "You've been running low-energy most evenings this week — want something more relaxed?",
            "sample_size": len(entries),
        }

    # 2) Mood dipped vs baseline.
    if (week_n >= 2 and base_valence is not None and week_valence is not None
            and week_valence <= base_valence - 0.25):
        return {
            "kind": "mood_dip",
            "text": "Your mood has been lower than usual this week — a gentle, low-key plan might help.",
            "sample_size": len(entries),
        }

    # 2b) Reaction ratings — how well the plans themselves are landing.
    if _reaction_pattern(entries):
        return _reaction_pattern(entries)

    # 3) A weekday that consistently runs low.
    weekday = by_weekday(user_id)
    worst = min(
        (row for row in weekday if row["count"] >= 2 and row["avg_valence"] is not None),
        key=lambda r: r["avg_valence"],
        default=None,
    )
    if worst and worst["avg_valence"] <= -0.4 and worst["day_of_week"] < 5:
        return {
            "kind": "weekday_pattern",
            "text": f"You tend to feel lowest on {worst['day']}s — I can plan something lighter for those.",
            "sample_size": len(entries),
        }

    # 4) Rain seems to correlate with lower mood.
    weather = weather_correlation(user_id)
    rainy = weather["rainy"]
    clear = weather["clear"]
    if (rainy["count"] >= 2 and clear["count"] >= 2
            and rainy["avg_valence"] is not None and clear["avg_valence"] is not None
            and rainy["avg_valence"] <= clear["avg_valence"] - 0.3):
        return {
            "kind": "weather_pattern",
            "text": "Rainy days seem to pull your mood down — indoor plans may suit you better then.",
            "sample_size": len(entries),
        }

    # 5) Positive trend.
    if (week_n >= 2 and base_valence is not None and week_valence is not None
            and week_valence >= base_valence + 0.25):
        return {
            "kind": "mood_up",
            "text": "Your mood has been trending up this week — want to try something a little more adventurous?",
            "sample_size": len(entries),
        }

    return None