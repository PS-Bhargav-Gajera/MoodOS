"""MoodOS MCP server: tools / resources / prompts.

External APIs are providers behind these tools — they are not MCP servers.
"""

from __future__ import annotations

from typing import Any, Callable

from moodos import actions, providers
from moodos.location_service import location_service
from moodos.memory import mem0
from moodos.nlu import extract_intent
from moodos.rag import knowledge


class MoodOSMCPServer:
    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., Any]] = {
            "analyze_mood": self.analyze_mood,
            "extract_preferences": self.extract_preferences,
            "get_user_profile": self.get_user_profile,
            "search_movies": self.search_movies,
            "suggest_movies": self.suggest_movies,
            "search_books": lambda q: providers.search_books(q),
            "search_music": lambda q, country="IN", limit=5: providers.search_music(q, country=country, limit=limit),
            "search_restaurants": self.search_restaurants,
            "search_restaurants_by_mood": self.search_restaurants_by_mood,
            "get_weather": lambda lat, lon: providers.get_weather(lat, lon),
            "find_nearby_places": lambda lat, lon, q=None, limit=24, radius_m=4000:
                location_service.search_nearby_places(lat, lon, categories=q, limit=limit, radius_m=radius_m),
            "find_nearby_cinemas": lambda lat, lon, limit=6: providers.nearby_cinemas(lat, lon, limit),
            "retrieve_knowledge": lambda q, k=8: knowledge.retrieve(q, k),
            "search_web_knowledge": lambda q: providers.web_snippets(q),
            "analyze_reviews": self.analyze_reviews,
            "prepare_movie_booking": lambda i=0: actions.prepare_movie_booking(i),
            "confirm_movie_booking": actions.confirm_movie_booking,
            "create_playlist": self.create_playlist,
            # TMDB home-viewing tools
            "search_home_movies": self.search_home_movies,
            "tmdb_movie_details": lambda tmdb_id: providers.tmdb_movie_details(tmdb_id),
            "tmdb_watch_providers": lambda tmdb_id, region="IN": providers.tmdb_watch_providers(tmdb_id, region),
            "tmdb_trending": lambda media_type="movie", time_window="week", limit=8: providers.tmdb_trending(media_type, time_window, limit),
            "tmdb_recommendations": lambda tmdb_id, limit=6: providers.tmdb_recommendations(tmdb_id, limit),
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

    def analyze_mood(self, message: str) -> dict:
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
        slots = extract_intent(message)
        return {
            "implicit_preferences": slots.get("implicit_preferences"),
            "budget_inr": slots.get("budget_inr"),
            "duration_hours": slots.get("duration_hours"),
            "social": slots.get("social"),
            "intensity": slots.get("intensity"),
        }

    def get_user_profile(self, user_id: str, query: str, categories: list[str] | None = None) -> dict:
        return {"user_id": user_id, "memories": mem0.retrieve(user_id, query, k=8, categories=categories)}

    def search_movies(self, query: str, watch_at_home: bool = False,
                      language: str | None = None) -> list:
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
        if mood:
            return providers.search_restaurants_by_mood(
                lat, lon, mood=mood, dietary=dietary, radius_m=radius_m, limit=limit
            )
        return providers.nearby_restaurants(
            lat, lon, cuisine=cuisine, dietary=dietary, radius_m=radius_m, limit=limit
        )

    def search_restaurants_by_mood(
        self, lat: float, lon: float, mood: str, dietary: str | None = None,
        radius_m: int = 5000, limit: int = 10,
    ) -> list:
        """Find restaurants matching a user's mood via mood→cuisine mapping."""
        return providers.search_restaurants_by_mood(
            lat, lon, mood=mood, dietary=dietary, radius_m=radius_m, limit=limit
        )

    def analyze_reviews(self, title: str, text: str) -> dict:
        blob = (title + " " + text).lower()
        aspects = {
            "story": "positive" if any(w in blob for w in ("story", "character", "heart")) else "mixed",
            "pacing": "slow" if "slow" in blob or "gentle" in blob else "moderate",
            "tone": "calming" if any(w in blob for w in ("calm", "quiet", "warm", "comfort")) else "neutral",
        }
        return {"title": title, "aspects": aspects, "summary": text[:280]}

    def create_playlist(self, query: str, confirm: bool = False, seed: int = 0) -> dict:
        from moodos import spotify as spotify_api

        tracks = providers.search_music(query, seed=seed)
        uris = [t.get("uri") for t in tracks if t.get("uri")]
        if not confirm:
            return {
                "status": "prepared",
                "requires_confirmation": True,
                "query": query,
                "seed": seed,
                "tracks": tracks[:8],
                "spotify_connected": spotify_api.user_connected(),
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
