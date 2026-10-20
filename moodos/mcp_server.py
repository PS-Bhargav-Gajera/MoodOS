"""MoodOS MCP server: tools / resources / prompts.

External APIs are providers behind these tools — they are not MCP servers.
"""

from __future__ import annotations

from typing import Any, Callable

from moodos import actions, providers
from moodos.geo import normalize_places, resolve_tool_coords
from moodos.location_service import location_service
from moodos.memory import mem0
from moodos.nlu import extract_intent
from moodos.rag import knowledge


class MoodOSMCPServer:
    def __init__(self) -> None:
        # Every entry is a real bound method or function — never a lambda — so
        # `inspect.signature` can derive a machine-readable input schema. MCP
        # Inspector (and any MCP client) needs that schema to render a form and
        # to validate arguments before dispatch; a lambda has no parameter
        # names, so `tool_schema()` would have to invent them.
        self.tools: dict[str, Callable[..., Any]] = {
            "analyze_mood": self.analyze_mood,
            "extract_preferences": self.extract_preferences,
            "get_user_profile": self.get_user_profile,
            "search_movies": self.search_movies,
            "suggest_movies": self.suggest_movies,
            "search_books": self.search_books,
            "search_music": self.search_music,
            "search_restaurants": self.search_restaurants,
            "search_restaurants_by_mood": self.search_restaurants_by_mood,
            "get_weather": self.get_weather,
            "find_nearby_places": self.find_nearby_places,
            "find_nearby_cinemas": self.find_nearby_cinemas,
            "retrieve_knowledge": self.retrieve_knowledge,
            "search_web_knowledge": self.search_web_knowledge,
            "analyze_reviews": self.analyze_reviews,
            "prepare_movie_booking": self.prepare_movie_booking,
            "confirm_movie_booking": self.confirm_movie_booking,
            "create_playlist": self.create_playlist,
            # TMDB home-viewing tools
            "search_home_movies": self.search_home_movies,
            "tmdb_movie_details": self.tmdb_movie_details,
            "tmdb_watch_providers": self.tmdb_watch_providers,
            "tmdb_trending": self.tmdb_trending,
            "tmdb_recommendations": self.tmdb_recommendations,
        }
        self.resources = {
            "user://profile": "Authorized user profile snapshot",
            "user://preferences": "Preference resource (Mem0-backed)",
            "experience://cozy-evening": "Reusable cozy evening pattern",
            "knowledge://mood/relaxation": "Relaxation theme knowledge",
        }
        self.prompts = [
            "/mood-night",
            "/date-night",
            "/study-session",
            "/rainy-day",
            "/weekend-plan",
            "/stress-relief",
            "/movie-night",
        ]

    def call(self, name: str, **kwargs: Any) -> Any:
        if name not in self.tools:
            raise KeyError(f"Unknown MCP tool: {name}")
        return self.tools[name](**kwargs)

    # --- schema ------------------------------------------------------------
    # A hand-rolled registry (there is no MCP SDK in this project), so the
    # input schema is DERIVED from the callable's signature rather than
    # hand-written. That way a signature change updates the published schema
    # automatically and a stale schema cannot ship.

    @staticmethod
    def _annotation_json(annotation: Any) -> dict:
        """Map a Python annotation onto a JSON Schema fragment."""
        name = getattr(annotation, "__name__", None) or str(annotation)
        name = name.replace("typing.", "")
        if name in ("float", "int"):
            return {"type": "number" if name == "float" else "integer"}
        if name == "str":
            return {"type": "string"}
        if name == "bool":
            return {"type": "boolean"}
        if name.startswith("list"):
            return {"type": "array"}
        if name.startswith("dict"):
            return {"type": "object"}
        return {}

    def tool_schema(self, name: str) -> dict:
        """MCP `tools/list` entry for one tool: name, description, inputSchema.

        Parameters without defaults are required. Defaults are echoed into the
        schema so an inspector can show the real default rather than guessing.
        """
        import inspect

        fn = self.tools[name]
        sig = inspect.signature(fn)
        props: dict[str, Any] = {}
        required: list[str] = []
        for pname, param in sig.parameters.items():
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            schema = self._annotation_json(param.annotation)
            if param.default is inspect.Parameter.empty:
                required.append(pname)
            else:
                schema["default"] = param.default
            props[pname] = schema
        doc = (inspect.getdoc(fn) or "").strip()
        out: dict[str, Any] = {
            "name": name,
            "description": doc.split("\n", 1)[0] if doc else name.replace("_", " "),
            "inputSchema": {"type": "object", "properties": props},
        }
        if required:
            out["inputSchema"]["required"] = required
        return out

    def list_tools(self) -> list[dict]:
        """Every tool as an MCP `tools/list` entry, sorted by name."""
        return [self.tool_schema(n) for n in sorted(self.tools)]

    def list_resources(self) -> list[dict]:
        return [{"uri": uri, "description": desc}
                for uri, desc in sorted(self.resources.items())]

    def list_prompts(self) -> list[dict]:
        return [{"name": p.lstrip("/"), "command": p} for p in self.prompts]

    def analyze_mood(self, message: str) -> dict:
        """Detect current and desired mood plus intensity from one message."""
        slots = extract_intent(message)
        return {
            "current_mood": slots.get("current_mood"),
            "desired_mood": slots.get("desired_mood"),
            "mood_intensity": slots.get("mood_intensity"),
            "mood_trajectory": slots.get("mood_trajectory"),
            "emotional_constraints": slots.get("constraints"),
            "agent": slots.get("_agent"),
        }

    def extract_preferences(self, message: str) -> dict:
        """Pull budget, duration, social shape and intensity out of a message."""
        slots = extract_intent(message)
        return {
            "implicit_preferences": slots.get("implicit_preferences"),
            "budget_inr": slots.get("budget_inr"),
            "duration_hours": slots.get("duration_hours"),
            "social": slots.get("social"),
            "intensity": slots.get("intensity"),
        }

    def get_user_profile(self, user_id: str, query: str, categories: list[str] | None = None) -> dict:
        """Retrieve Mem0 memories for one user, optionally filtered by category."""
        return {"user_id": user_id, "memories": mem0.retrieve(user_id, query, k=8, categories=categories)}

    def search_movies(self, query: str, watch_at_home: bool = False,
                      language: str | None = None) -> list:
        """Search TMDB for a title, falling back to local RAG movie records."""
        live = providers.search_movies_tmdb(query, watch_at_home=watch_at_home, language=language)
        rag, _ = knowledge.retrieve(query, k=6, kinds=["movie"])
        return live or rag

    def suggest_movies(self, query: str, limit: int = 8, watch_at_home: bool = False,
                       language: str | None = None, region: str = "IN") -> list:
        """Mood-aware movie suggestions for a plan (the tool run_pipeline calls).

        Routes to the streaming-aware home search when the user is staying in,
        otherwise to the plain TMDB search. Kept distinct from search_movies so
        the plan path can request a limit/region without changing the legacy
        endpoint contract.
        """
        if watch_at_home:
            return self.search_home_movies(query, limit=limit, language=language)
        return providers.search_movies_tmdb(query, limit=limit,
                                            watch_at_home=False, language=language)

    def search_home_movies(self, query: str, limit: int = 8,
                           language: str | None = None) -> list:
        """Search for movies to watch at home — marks all results as streaming candidates
        and enriches top results with watch provider data."""
        movies = providers.search_movies_tmdb(query, limit=limit, watch_at_home=True, language=language)
        # Also include trending movies as fallback
        if len(movies) < 4:
            trending = providers.tmdb_trending("movie", "week", limit=6)
            seen = {m["id"] for m in movies}
            for t in trending:
                if t["id"] not in seen:
                    movies.append(t)
        # Enrich top results with streaming availability
        for movie in movies[:4]:
            tmdb_id = movie.get("tmdb_id")
            if tmdb_id:
                wp = providers.tmdb_watch_providers(tmdb_id)
                if wp:
                    providers_list = wp.get("flatrate") or wp.get("rent") or []
                    movie["streaming"] = [p.get("name") for p in providers_list[:3]]
                    movie["watch_link"] = wp.get("link")
        return movies

    def find_nearby_places(
        self,
        lat: float,
        lon: float,
        q: str | list[str] | None = None,
        limit: int = 24,
        radius_m: int = 4000,
    ) -> list:
        """Real POIs around the shared resolved coordinates (Overpass/OSM)."""
        lat, lon = resolve_tool_coords(lat, lon, tool="find_nearby_places")
        raw = location_service.search_nearby_places(
            lat, lon, categories=q, limit=limit, radius_m=radius_m, strict=True,
        )
        return normalize_places(raw, lat, lon, radius_km=radius_m / 1000.0, limit=limit)

    def find_nearby_cinemas(
        self, lat: float, lon: float, limit: int = 6, radius_m: int = 15000,
    ) -> list:
        """Real cinema venues around the shared resolved coordinates (Overpass/OSM)."""
        lat, lon = resolve_tool_coords(lat, lon, tool="find_nearby_cinemas")
        raw = providers.nearby_cinemas(lat, lon, limit=limit, strict=True)
        return normalize_places(raw, lat, lon, radius_km=radius_m / 1000.0, limit=limit)

    def get_weather(self, lat: float, lon: float) -> dict:
        """Live conditions at the shared resolved coordinates (Open-Meteo)."""
        lat, lon = resolve_tool_coords(lat, lon, tool="get_weather")
        return providers.get_weather(lat, lon, strict=True)

    def search_restaurants(
        self,
        lat: float,
        lon: float,
        cuisine: str | None = None,
        mood: str | None = None,
        dietary: str | None = None,
        radius_m: int = 5000,
        limit: int = 10,
    ) -> list:
        """Search for nearby restaurants with optional cuisine, mood, and dietary filters."""
        lat, lon = resolve_tool_coords(lat, lon, tool="search_restaurants")
        if mood:
            raw = providers.search_restaurants_by_mood(
                lat, lon, mood=mood, dietary=dietary, radius_m=radius_m,
                limit=limit, strict=True,
            )
        else:
            raw = providers.nearby_restaurants(
                lat, lon, cuisine=cuisine, dietary=dietary, radius_m=radius_m,
                limit=limit, strict=True,
            )
        return normalize_places(raw, lat, lon, radius_km=radius_m / 1000.0, limit=limit)

    def search_restaurants_by_mood(
        self, lat: float, lon: float, mood: str, dietary: str | None = None,
        radius_m: int = 5000, limit: int = 10,
    ) -> list:
        """Find restaurants matching a user's mood via mood→cuisine mapping."""
        lat, lon = resolve_tool_coords(lat, lon, tool="search_restaurants_by_mood")
        raw = providers.search_restaurants_by_mood(
            lat, lon, mood=mood, dietary=dietary, radius_m=radius_m,
            limit=limit, strict=True,
        )
        return normalize_places(raw, lat, lon, radius_km=radius_m / 1000.0, limit=limit)

    def analyze_reviews(self, title: str, text: str) -> dict:
        """Score one review's story, pacing and tone for a title."""
        blob = (title + " " + text).lower()
        aspects = {
            "story": "positive" if any(w in blob for w in ("story", "character", "heart")) else "mixed",
            "pacing": "slow" if any(w in blob for w in ("slow", "gentle")) else "moderate",
            "tone": "calming" if any(w in blob for w in ("calm", "quiet", "warm", "comfort")) else "neutral",
        }
        return {"title": title, "aspects": aspects, "summary": text[:280]}

    def search_books(self, query: str, limit: int = 5) -> list[dict]:
        """Book search for a comfort/quiet reading leg."""
        return providers.search_books(query, limit=limit)

    def search_music(self, query: str, country: str = "IN", limit: int = 5) -> list[dict]:
        """Live Spotify track search. No fallback catalogue."""
        return providers.search_music(query, country=country, limit=limit)

    def retrieve_knowledge(self, query: str, k: int = 8) -> list[dict]:
        """RAG retrieval over the local knowledge index."""
        hits, _conf = knowledge.retrieve(query, k=k)
        return hits

    def search_web_knowledge(self, query: str, limit: int = 4) -> list[dict]:
        """Web snippets used as an adaptive fallback when RAG is thin."""
        return providers.web_snippets(query, limit=limit)

    def prepare_movie_booking(self, show_index: int = 0) -> dict:
        """Stage a cinema booking for confirmation; nothing is purchased."""
        return actions.prepare_movie_booking(show_index)

    def confirm_movie_booking(self, confirmed: bool, show: dict | None = None) -> dict:
        """Confirm or abort a previously prepared cinema booking."""
        return actions.confirm_movie_booking(confirmed, show)

    def tmdb_movie_details(self, tmdb_id: int) -> dict:
        """Full TMDB detail record for one movie id."""
        return providers.tmdb_movie_details(tmdb_id)

    def tmdb_watch_providers(self, tmdb_id: int, region: str = "IN") -> dict:
        """Where to stream/rent one movie in a given region."""
        return providers.tmdb_watch_providers(tmdb_id, region)

    def tmdb_trending(self, media_type: str = "movie", time_window: str = "week",
                      limit: int = 8) -> list[dict]:
        """TMDB trending titles, used as a home-viewing fallback."""
        return providers.tmdb_trending(media_type, time_window, limit)

    def tmdb_recommendations(self, tmdb_id: int, limit: int = 6) -> list[dict]:
        """Titles TMDB considers similar to the given movie id."""
        return providers.tmdb_recommendations(tmdb_id, limit)

    def create_playlist(self, query: str, confirm: bool = False, seed: int = 0) -> dict:
        """Prepare or create a Spotify playlist from a mood query.

        With confirm=False the playlist is only staged for review (nothing is
        written to the user's account); confirm=True performs the write.
        """
        from moodos import spotify as spotify_api

        tracks = providers.search_music(query, seed=seed)
        uris = [t.get("uri") for t in tracks if t.get("uri")]
        if not tracks:
            # Spotify is the only music source, so an empty result is either a
            # genuine no-match or a dead/rate-limited provider. Confirming an
            # empty playlist would create a real, empty playlist on the user's
            # account, so refuse to prepare one and say why.
            return {
                **spotify_api.friendly(
                    "create_failed",
                    message=(
                        "Spotify didn't return any tracks for that mood right now. "
                        "Nothing was created — try again in a moment."
                    ),
                    action="retry",
                ),
                "requires_confirmation": False,
                "executed": False,
                "query": query,
                "tracks": [],
                "spotify_connected": spotify_api.can_create_playlists(),
                "scope_gap": spotify_api.scope_gap(),
                "authorize_url": spotify_api.authorize_url() if spotify_api.configured() else None,
                "provider": "none",
            }
        if not confirm:
            return {
                **spotify_api.friendly("prepared"),
                "requires_confirmation": True,
                "query": query,
                "seed": seed,
                "tracks": tracks[:8],
                # can_create_playlists(), not user_connected(): a grant without
                # the playlist scopes is connected but cannot do this job, and
                # saying "connected" only to fail at create wastes the user's
                # click and hides the real reason.
                "spotify_connected": spotify_api.can_create_playlists(),
                "scope_gap": spotify_api.scope_gap(),
                "authorize_url": spotify_api.authorize_url() if spotify_api.configured() else None,
                "provider": (tracks[0].get("source") if tracks else "none"),
            }
        return spotify_api.create_playlist(
            _playlist_name(query), uris, confirm=True
        )


def _playlist_name(query: str) -> str:
    q = query.lower()
    if any(w in q for w in ("lo-fi", "lofi", "focus", "study")):
        return "MoodOS — lo-fi focus"
    if any(w in q for w in ("upbeat", "energetic", "dance", "party", "pop")):
        return "MoodOS — upbeat mix"
    if any(w in q for w in ("acoustic", "folk", "piano", "guitar", "ambient")):
        return "MoodOS — calm acoustic"
    return "MoodOS — chill mix"


mcp = MoodOSMCPServer()
