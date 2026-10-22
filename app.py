from __future__ import annotations

import logging
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from moodos import actions
from moodos import journal
from moodos import spotify as spotify_api
from moodos.config import settings
from moodos.crisis import crisis_reply, is_crisis
from moodos.db import get_event, get_mood_entry, init_db, save_feedback
from moodos.geo import LocationError, ProviderUnavailable
from moodos.location import resolve_location
from moodos.llm import router
from moodos.memory import mem0
from moodos.mcp_server import mcp
from moodos.weather_mcp import weather_mcp_client, weather_mcp_server
from moodos.orchestrator import handle_message

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

log = logging.getLogger("moodos.app")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="MoodOS", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# Everything a user gets to see when something blows up. The detail that
# actually helps goes to the log, keyed by the same error id we're about to
# hand back, so a bug report can be traced to one line.
GENERIC_ERROR_MESSAGE = (
    "Something went wrong on our side. We've logged the details — please try again."
)


def _error_id() -> str:
    return uuid.uuid4().hex[:8]


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_id = _error_id()
    log.error(
        "Unhandled exception [id=%s] on %s: %s\n%s",
        error_id,
        request.url,
        exc,
        traceback.format_exc(),
    )
    # No str(exc) and no exception class name here: both leak internals (DB
    # drivers, hostnames, file paths) to any API consumer.
    return JSONResponse(
        status_code=500,
        content={
            "error": GENERIC_ERROR_MESSAGE,
            "code": "internal_error",
            "error_id": error_id,
            "plan": None,
            "explanation": GENERIC_ERROR_MESSAGE,
        },
    )


@app.exception_handler(LocationError)
async def location_error_handler(request: Request, exc: LocationError):
    """A missing/impossible location is the caller's to fix, not a 500.

    428 Precondition Required = "give us a location"; 400 = the coordinates or
    the typed place were invalid. Either way the real reason is returned.
    """
    log.warning("location rejected on %s: %s", request.url, exc)
    status = 428 if exc.code == "location_required" else 400
    return JSONResponse(
        status_code=status,
        content={**exc.as_dict(), "plan": None, "explanation": exc.message},
    )


@app.exception_handler(ProviderUnavailable)
async def provider_error_handler(request: Request, exc: ProviderUnavailable):
    """A dead provider is reported honestly instead of as an empty success."""
    log.warning("provider unavailable on %s: %s", request.url, exc)
    return JSONResponse(
        status_code=503,
        content={**exc.as_dict(), "explanation": exc.message},
    )


class PlanRequest(BaseModel):
    message: str
    user_id: str = "demo"
    lat: float | None = None
    lon: float | None = None
    prompt: str | None = None
    user_label: str | None = None
    city: str | None = None
    ip: str | None = None
    accuracy_m: float | None = None


class LocationResolveRequest(BaseModel):
    lat: float | None = None
    lon: float | None = None
    user_label: str | None = None
    ip: str | None = None
    accuracy_m: float | None = None


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
def plan(req: PlanRequest, request: Request, background: BackgroundTasks) -> dict:
    if not req.message.strip():
        raise HTTPException(400, "message required")
    from moodos.terminal_stream import terminal_bus
    import time
    t0 = time.perf_counter()
    typed = (req.user_label or "").strip() or (req.city or "").strip()
    terminal_bus.log_client_send(
        req.message.strip(),
        user_id=req.user_id,
        lat=req.lat,
        lon=req.lon,
        user_label=typed or None,
        prompt=req.prompt,
        endpoint="/api/plan",
    )
    # Crisis check BEFORE resolve_location: a person in crisis must never get
    # a location error (409/428) or wait on a geocode lookup. One shared
    # helper (moodos.crisis) — no copy-pasted phrase lists.
    if is_crisis(req.message):
        return crisis_reply()
    ip = req.ip or request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host
    ip = None if ip in {"127.0.0.1", "::1", "localhost"} or not ip else ip
    # A typed place in THIS request outranks the GPS fix, so it must reach the
    # shared resolver as the typed label — not just as a display string.
    typed = (req.user_label or "").strip() or (req.city or "").strip()
    resolved = resolve_location(req.lat, req.lon, typed or None, ip, accuracy_m=req.accuracy_m)
    if resolved.get("needs_confirmation"):
        # Ambiguous typed name: hand back the full resolved addresses so the
        # user can confirm, instead of silently planning around one of them.
        return JSONResponse(
            status_code=409,
            content={
                "error": "location_ambiguous",
                "message": resolved.get("notice"),
                "candidates": resolved.get("candidates") or [],
                "query": typed,
                "explanation": resolved.get("notice"),
            },
        )
    location_names = {}
    if typed:
        location_names = {
            "city": resolved.get("city") or typed,
            "area": resolved.get("area") or typed,
            "label": typed,
            "source": "user",
        }
    bundle = handle_message(
        req.message.strip(),
        req.user_id,
        resolved["lat"],
        resolved["lon"],
        req.prompt,
        location_names=location_names if location_names else resolved,
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
            "notice": resolved.get("notice"),
        }
        # Fire-and-forget AFTER the response is built, so a slow/failed Mem0
        # call can never delay or break the plan the user is waiting on.
        background.add_task(_remember_suggestions_bg, req.user_id, bundle)

    elapsed_s = time.perf_counter() - t0
    mode = bundle.get("mode", "plan") if isinstance(bundle, dict) else "unknown"
    if mode == "chat":
        summary = f"Direct answer: {(bundle.get('reply') or '')[:80]}..."
    else:
        steps_len = len((bundle.get("plan") or {}).get("steps") or [])
        weather_cond = (bundle.get("weather") or {}).get("condition", "unknown")
        summary = f"{steps_len} steps planned, weather: {weather_cond}"
    terminal_bus.log_response_sent(200, elapsed_s, summary, mode=mode)
    return bundle


def _remember_suggestions_bg(user_id: str, bundle: dict) -> None:
    """Persist what we just showed to Mem0, in the background.

    Runs as a FastAPI BackgroundTask: any failure is logged and swallowed.
    Repeat-suppression itself does NOT depend on this (that is handled by the
    durable SQLite shown_items log in the orchestrator) — this is an extra
    audit trail so a "what did you show me" memory exists in Mem0 too.
    """
    try:
        steps = ((bundle.get("plan") or {}).get("steps")) or []
        movies = [
            s.get("title") for s in steps
            if str(s.get("kind") or "").lower() in {"movie", "streaming"} and s.get("title")
        ]
        if movies:
            mem0.add(
                user_id,
                "Suggested movie: " + ", ".join(movies[:3]),
                kind="episodic",
                confidence=0.5,
                category="episodic",
                metadata={"kind": "suggested_movie", "titles": movies[:3]},
                source="plan",
            )
        tracks = [
            t.get("title")
            for s in steps if str(s.get("kind") or "").lower() == "music"
            for t in (s.get("tracks") or []) if t.get("title")
        ]
        if tracks:
            mem0.add(
                user_id,
                "Suggested songs: " + ", ".join(tracks[:8]),
                kind="episodic",
                confidence=0.5,
                category="episodic",
                metadata={"kind": "suggested_tracks", "count": len(tracks)},
                source="plan",
            )
    except Exception as exc:  # never surface to the caller
        log.warning("background mem0 suggestion write failed: %s", exc)


@app.post("/api/location/resolve")
def location_resolve(req: LocationResolveRequest, request: Request) -> dict:
    ip = req.ip or request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host
    ip = None if ip in {"127.0.0.1", "::1", "localhost"} or not ip else ip
    return resolve_location(req.lat, req.lon, req.user_label, ip, accuracy_m=req.accuracy_m)


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


@app.delete("/api/memory/all")
async def delete_all_memories(user_id: str = "demo"):
    """Delete all memories for a user at once."""
    try:
        result = mem0.delete(user_id)
        return {
            "success": True,
            "deleted": result,
            "message": "All memories cleared."
        }
    except Exception as exc:
        error_id = _error_id()
        log.error("delete all memories failed [id=%s]: %s", error_id, exc, exc_info=True)
        return {"success": False, "error": GENERIC_ERROR_MESSAGE, "error_id": error_id}


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


# Spotify's own error codes (access_denied, invalid_state, ...) are meant for
# logs. They reach the browser as HTTPException detail, so map them to prose.
_SPOTIFY_AUTH_ERRORS = {
    "access_denied": "You declined the Spotify connection. Nothing was changed.",
    "invalid_state": "That Spotify sign-in link has expired. Start again from the app.",
    "exchange_failed": "Spotify rejected the sign-in. Start again from the app.",
    "exchange_error": "Couldn't reach Spotify to finish signing in. Try again.",
}
_SPOTIFY_AUTH_FALLBACK = "Couldn't finish connecting Spotify. Try again from the app."


@app.get("/spotify/callback")
def spotify_callback(code: str = "", state: str = "", error: str = ""):
    if error:
        log.info("spotify oauth declined by user: %s", error)
        raise HTTPException(400, _SPOTIFY_AUTH_ERRORS.get(error, _SPOTIFY_AUTH_FALLBACK))
    result = spotify_api.exchange_code(code, state)
    if not result.get("ok"):
        raw = result.get("error") or "spotify_auth_failed"
        log.warning("spotify auth callback failed: %s", raw)
        raise HTTPException(400, _SPOTIFY_AUTH_ERRORS.get(raw, _SPOTIFY_AUTH_FALLBACK))
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


# --- MCP tool discovery ---------------------------------------------------
# There is no MCP SDK in this project: MoodOSMCPServer is an in-process
# registry with no transport. These endpoints publish the registry in the
# shape an MCP client (or MCP Inspector's "HTTP transport" tab) expects, so
# the schema can be inspected and validated without a live server handshake.
# They are read-only listings; `mcp.call` remains the only dispatch path.

@app.get("/mcp/tools")
def mcp_tools() -> dict:
    """MCP `tools/list` result: every tool with a derived inputSchema."""
    return {"tools": mcp.list_tools()}


@app.get("/mcp/resources")
def mcp_resources() -> dict:
    """MCP `resources/list` result."""
    return {"resources": mcp.list_resources()}


@app.get("/mcp/prompts")
def mcp_prompts() -> dict:
    """MCP `prompts/list` result."""
    return {"prompts": mcp.list_prompts()}


@app.get("/mcp/tools/{name}")
def mcp_tool_schema(name: str) -> dict:
    """Schema for one tool, or 404 if it is not registered."""
    if name not in mcp.tools:
        raise HTTPException(404, f"Unknown MCP tool: {name}")
    return mcp.tool_schema(name)


# --- Open-Meteo Weather MCP Endpoints ----------------------------------------

@app.post("/mcp/weather")
def mcp_weather_jsonrpc(payload: dict) -> dict:
    """Standard Model Context Protocol JSON-RPC 2.0 handler for Open-Meteo Weather."""
    return weather_mcp_server.handle_jsonrpc(payload)


@app.get("/mcp/weather/tools")
def mcp_weather_tools() -> dict:
    """List tools with their schemas provided by the Open-Meteo Weather MCP Server."""
    return {"tools": weather_mcp_server.list_tools()}


@app.post("/mcp/weather/call")
def mcp_weather_call(payload: dict) -> dict:
    """Execute a Weather MCP tool directly by name."""
    tool_name = payload.get("tool") or payload.get("name")
    if not tool_name:
        raise HTTPException(400, "Missing 'tool' or 'name' in request body")
    arguments = payload.get("arguments") or payload.get("args") or {}
    try:
        res = weather_mcp_server.call_tool(tool_name, arguments)
        return {"ok": True, "tool": tool_name, "result": res}
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Tool execution failed: {exc}")


@app.get("/api/weather/current")
def api_weather_current(lat: float, lon: float) -> dict:
    """REST endpoint for current weather conditions via Open-Meteo Weather MCP."""
    return weather_mcp_client.get_current_weather(lat=lat, lon=lon)


@app.get("/api/weather/forecast")
def api_weather_forecast(lat: float, lon: float, days: int = 7) -> dict:
    """REST endpoint for multi-day weather forecast via Open-Meteo Weather MCP."""
    return weather_mcp_client.get_forecast(lat=lat, lon=lon, days=days)


@app.get("/api/weather/hourly")
def api_weather_hourly(lat: float, lon: float, hours: int = 24) -> dict:
    """REST endpoint for hourly weather forecast via Open-Meteo Weather MCP."""
    return weather_mcp_client.get_hourly(lat=lat, lon=lon, hours=hours)


@app.get("/api/weather/activity")
def api_weather_activity(lat: float, lon: float, activity: str = "outdoor_walk") -> dict:
    """REST endpoint to evaluate weather suitability for an intended activity."""
    return weather_mcp_client.evaluate_activity(lat=lat, lon=lon, activity=activity)


# --- Live Terminal Stream Endpoints ------------------------------------------

@app.get("/api/live-terminal/stream")
async def live_terminal_stream():
    """SSE endpoint streaming live terminal events to watching terminal clients or UI."""
    import asyncio
    import json
    from fastapi.responses import StreamingResponse
    from moodos.terminal_stream import terminal_bus

    async def event_generator():
        q = terminal_bus.subscribe()
        try:
            # Replay recent history so new viewers get context
            for old in terminal_bus.get_history():
                yield f"data: {json.dumps(old)}\n\n"
            while True:
                item = await q.get()
                yield f"data: {json.dumps(item)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            terminal_bus.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/live-terminal/history")
def live_terminal_history():
    from moodos.terminal_stream import terminal_bus
    return {"history": terminal_bus.get_history()}



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
    city: str | None = None,
    cuisine: str | None = None,
    mood: str | None = None,
    dietary: str | None = None,
    radius: int = 5000,
    limit: int = 10,
) -> dict:
    # Same shared resolver as /api/plan: typed city > GPS > IP > profile,
    # with an honest 428 instead of silently searching Ahmedabad.
    resolved = resolve_location(lat, lon, (city or "").strip() or None, None)
    results = mcp.call(
        "search_restaurants",
        lat=resolved["lat"],
        lon=resolved["lon"],
        cuisine=cuisine,
        mood=mood,
        dietary=dietary,
        radius_m=radius,
        limit=limit,
    )
    return {
        "restaurants": results,
        "count": len(results),
        "lat": resolved["lat"],
        "lon": resolved["lon"],
        "location": {
            "source": resolved["source"],
            "label": resolved["label"],
            "city": resolved.get("city"),
            "confidence": resolved["confidence"],
        },
        "notice": resolved.get("notice"),
    }
