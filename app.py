from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from moodos import actions
from moodos import journal
from moodos import spotify as spotify_api
from moodos.config import settings
from moodos.db import get_event, get_mood_entry, init_db, save_feedback
from moodos.location import resolve_location
from moodos.llm import router
from moodos.memory import mem0
from moodos.mcp_server import mcp
from moodos.orchestrator import handle_message

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

app = FastAPI(title="MoodOS", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class PlanRequest(BaseModel):
    message: str
    user_id: str = "demo"
    lat: float | None = None
    lon: float | None = None
    prompt: str | None = None
    user_label: str | None = None
    ip: str | None = None


class LocationResolveRequest(BaseModel):
    lat: float | None = None
    lon: float | None = None
    user_label: str | None = None
    ip: str | None = None


class FeedbackRequest(BaseModel):
    user_id: str = "demo"
    event_id: int | None = None
    signal: str
    note: str = ""
    repeats: int = Field(default=1, ge=1, le=10)


class MemoryUpdateRequest(BaseModel):
    user_id: str = "demo"
    text: str | None = None
    metadata: dict | None = None


class BookingConfirm(BaseModel):
    confirmed: bool
    show_index: int = 0


class PlaylistConfirm(BaseModel):
    query: str = "calm acoustic evening"
    confirmed: bool = False


class JournalReactRequest(BaseModel):
    user_id: str = "demo"
    entry_id: int
    reaction: str


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "groq": router.groq_ready,
        "gemini": router.gemini_ready,
        "mem0": mem0.cloud_ready,
        "spotify": spotify_api.configured(),
        "spotify_user": spotify_api.user_connected(),
        "cost": "free-tier / local retrieval",
    }


@app.post("/api/plan")
def plan(req: PlanRequest, request: Request) -> dict:
    if not req.message.strip():
        raise HTTPException(400, "message required")
    ip = req.ip or request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host
    ip = None if ip in {"127.0.0.1", "::1", "localhost"} or not ip else ip
    resolved = resolve_location(req.lat, req.lon, req.user_label, ip)
    bundle = handle_message(
        req.message.strip(),
        req.user_id,
        resolved["lat"],
        resolved["lon"],
        req.prompt,
        location_names=resolved,
    )
    if isinstance(bundle, dict):
        bundle.setdefault("location", {})["resolver"] = {
            "source": resolved["source"],
            "confidence": resolved["confidence"],
            "label": resolved["label"],
            "gps_live": resolved["gps_live"],
            "user_override": resolved["user_override"],
            "city": resolved["city"],
            "area": resolved["area"],
            "state": resolved["state"],
        }
    return bundle


@app.post("/api/location/resolve")
def location_resolve(req: LocationResolveRequest, request: Request) -> dict:
    ip = req.ip or request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host
    ip = None if ip in {"127.0.0.1", "::1", "localhost"} or not ip else ip
    return resolve_location(req.lat, req.lon, req.user_label, ip)


@app.post("/api/feedback")
def feedback(req: FeedbackRequest) -> dict:
    from moodos.memory_writer import remember_plan_outcome

    long_term = False
    is_new = False
    stored = None
    event = get_event(req.event_id) if req.event_id else None
    if req.note.strip():
        result = mem0.add_if_long_term(req.user_id, req.note.strip(), req.repeats)
        long_term = result["long_term"]
        is_new = result["new"]
        stored = req.note.strip()
    elif req.signal == "like":
        stored = "User enjoyed the last suggested experience"
        result = mem0.add_if_long_term(req.user_id, stored, req.repeats)
        long_term = result["long_term"]
        is_new = result["new"]
    elif req.signal in {"dislike", "disliked", "rejected"}:
        stored = "User did not enjoy the last suggested experience"
        result = mem0.add_if_long_term(req.user_id, stored, req.repeats)
        long_term = result["long_term"]
        is_new = result["new"]
    save_feedback(req.user_id, req.event_id, req.signal, req.note, long_term)

    outcome = {"like": "liked", "disliked": "disliked", "dislike": "disliked",
               "accepted": "accepted", "rejected": "rejected"}.get(req.signal)
    if outcome:
        try:
            remember_plan_outcome(
                req.user_id,
                (event or {}).get("query"),
                (event or {}).get("slots"),
                (event or {}).get("plan"),
                outcome=outcome,
                event_id=req.event_id,
            )
        except Exception:
            pass
    return {"ok": True, "long_term": long_term, "new": is_new, "stored": stored if long_term else None}


@app.get("/api/mem0")
def mem0_list(user_id: str = "demo", categories: str | None = None) -> dict:
    cats = categories.split(",") if categories else None
    rows = mem0.list(user_id, categories=cats)
    for row in rows:
        row["category"] = row.get("category") or "preference"
    return {"ok": True, "memories": rows}


@app.post("/api/mem0/remove")
def mem0_remove(user_id: str = "demo") -> dict:
    removed = mem0.delete(user_id)
    return {"ok": True, **removed}


@app.put("/api/mem0/{memory_id}")
def mem0_update_one(memory_id: str, req: MemoryUpdateRequest) -> dict:
    updated = mem0.update(req.user_id, memory_id, text=req.text, metadata=req.metadata)
    return {"ok": updated}


@app.delete("/api/mem0/{memory_id}")
def mem0_delete_one(memory_id: str, user_id: str = "demo") -> dict:
    removed = mem0.remove_one(user_id, memory_id)
    return {"ok": removed}


@app.post("/api/booking/prepare")
def booking_prepare(show_index: int = 0) -> dict:
    return actions.prepare_movie_booking(show_index)


@app.post("/api/booking/confirm")
def booking_confirm(body: BookingConfirm) -> dict:
    show = actions.list_showtimes()[body.show_index % 2]
    return actions.confirm_movie_booking(body.confirmed, show)


@app.get("/spotify/login")
def spotify_login():
    if not spotify_api.configured():
        raise HTTPException(400, "Spotify is not configured")
    return RedirectResponse(spotify_api.authorize_url())


@app.get("/spotify/callback")
def spotify_callback(code: str = "", state: str = "", error: str = ""):
    if error:
        raise HTTPException(400, error)
    result = spotify_api.exchange_code(code, state)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "spotify_auth_failed")
    return RedirectResponse("/")


@app.post("/api/playlist/prepare")
def playlist_prepare(query: str = "calm acoustic evening", seed: int = 0) -> dict:
    return mcp.call("create_playlist", query=query, seed=seed, confirm=False)


@app.post("/api/playlist/confirm")
def playlist_confirm(body: PlaylistConfirm) -> dict:
    return mcp.call("create_playlist", query=body.query, confirm=body.confirmed)


@app.get("/api/prompts")
def prompts() -> dict:
    return {"prompts": mcp.prompts, "tools": list(mcp.tools)}


@app.get("/api/journal")
def journal_list(user_id: str = "demo", limit: int = 100, offset: int = 0) -> dict:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    return {"ok": True, "entries": journal.recent_entries(user_id, limit=limit, offset=offset)}


@app.get("/api/journal/trends")
def journal_trends(user_id: str = "demo", weeks: int = 4) -> dict:
    weeks = max(1, min(weeks, 52))
    return {"ok": True, **journal.trends(user_id, weeks=weeks)}


@app.get("/api/journal/strip")
def journal_strip(user_id: str = "demo", limit: int = 12) -> dict:
    limit = max(1, min(limit, 50))
    return {"ok": True, **journal.summary_strip(user_id, limit=limit)}


@app.post("/api/journal/react")
def journal_react(req: JournalReactRequest) -> dict:
    if req.reaction not in journal.REACTION_LABELS:
        raise HTTPException(400, f"reaction must be one of {', '.join(journal.REACTION_LABELS)}")
    applied = journal.react_to_entry(req.user_id, req.entry_id, req.reaction)
    learned = None
    if applied and req.reaction == "happy":
        learned = _learn_from_reaction(req.user_id, req.entry_id)
    return {"ok": True, "applied": applied, "reaction": req.reaction, "learned": learned}


def _learn_from_reaction(user_id: str, entry_id: int) -> dict | None:
    """Best-effort: read the plan from the entry's event and learn prefs.
    Errors never leak into the API response."""
    try:
        from moodos.memory_writer import learn_from_reaction as do_learn
        entry = get_mood_entry(user_id, entry_id)
        if not entry or not entry.get("event_id"):
            return None
        event = get_event(entry["event_id"])
        if not event:
            return None
        return do_learn(
            user_id,
            event.get("plan"),
            event.get("slots"),
            event_id=entry["event_id"],
            entry_id=entry_id,
        )
    except Exception:
        return None


@app.delete("/api/journal/{entry_id}")
def journal_delete_one(entry_id: int, user_id: str = "demo") -> dict:
    return {"ok": journal.delete_entry(user_id, entry_id)}


@app.delete("/api/journal")
def journal_clear(user_id: str = "demo") -> dict:
    return {"ok": True, "removed": journal.clear_journal(user_id)}


@app.get("/api/restaurants")
def restaurants(
    lat: float | None = None,
    lon: float | None = None,
    cuisine: str | None = None,
    mood: str | None = None,
    dietary: str | None = None,
    radius: int = 5000,
    limit: int = 10,
) -> dict:
    lat = lat if lat is not None else settings.default_lat
    lon = lon if lon is not None else settings.default_lon
    results = mcp.call(
        "search_restaurants",
        lat=lat,
        lon=lon,
        cuisine=cuisine,
        mood=mood,
        dietary=dietary,
        radius_m=radius,
        limit=limit,
    )
    return {"restaurants": results, "count": len(results), "lat": lat, "lon": lon}
