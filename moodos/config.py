from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Project .env must win over a stale machine-level GROQ_API_KEY.
load_dotenv(ROOT / ".env", override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    groq_api_key: str = ""
    gemini_api_key: str = ""
    mem0_api_key: str = ""
    tmdb_api_key: str = ""
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "http://127.0.0.1:8000/spotify/callback"

    groq_fast_model: str = "openai/gpt-oss-20b"
    groq_reason_model: str = "openai/gpt-oss-120b"
    gemini_plan_model: str = "gemini-2.5-flash"
    gemini_fallback_models: str = (
        "gemini-2.5-flash-lite,gemini-2.5-flash,gemini-3.5-flash,"
        "gemini-3.1-flash-lite,gemini-flash-latest,gemini-2.0-flash"
    )

    default_city: str = "Ahmedabad"
    default_lat: float = 23.0225
    default_lon: float = 72.5714

    # Public OSM-family endpoints. All env-overridable so a self-hosted
    # Overpass/OSRM/Nominatim can be pointed to without code changes.
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    # Comma-separated fallbacks, tried after overpass_url. The public instance
    # rate-limits hard and 504s under load, so point this at a self-hosted or
    # paid instance for reliability.
    overpass_mirrors: str = (
        "https://overpass.kumi.systems/api/interpreter,"
        "https://overpass.private.coffee/api/interpreter"
    )
    # Per-HTTP-attempt timeout, and the total wall clock one Overpass query may
    # consume across every mirror and retry. The budget is what stops a flaky
    # public OSM from stalling a whole /api/plan request.
    overpass_timeout_s: float = 8.0
    overpass_budget_s: float = 8.0
    # Consecutive whole-query failures before the breaker opens, and how long
    # it stays open before we try OSM again.
    overpass_trip_after: int = 3
    overpass_cooldown_s: float = 120.0
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    osrm_url: str = "https://router.project-osrm.org"
    # Minimum gap between public OSM API hits (ms) to keep rate limits happy.
    osm_min_interval_ms: int = 900

    sqlite_path: Path = DATA_DIR / "moodos.db"
    cache_path: Path = DATA_DIR / "ttl_cache.json"


settings = Settings()
