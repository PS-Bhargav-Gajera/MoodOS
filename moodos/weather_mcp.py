"""Open-Meteo Weather MCP (Model Context Protocol) Server & Client.

Provides a full MCP architecture for Open-Meteo weather intelligence:
- Tools with rich input schemas, parameters, and weather understanding
- OpenMeteoWeatherMCPServer exposing standard MCP JSON-RPC 2.0 protocol
- OpenMeteoWeatherMCPClient for in-process or remote MCP tool invocation
- WMO Weather Code interpretation and activity suitability scoring
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

import httpx

from moodos.cache import ttl_cache
from moodos.geo import ProviderUnavailable, resolve_tool_coords

log = logging.getLogger("moodos.weather_mcp")

OPEN_METEO_TIMEOUT_S = 12.0
HEADERS = {"User-Agent": "MoodOS/0.1 (student project; https://github.com/PS-Bhargav-Gajera/moodos)"}

# ---------------------------------------------------------------------------
# WMO Weather Code Knowledge Base & Semantic Understanding
# ---------------------------------------------------------------------------

WMO_WEATHER_CODES: dict[int, dict[str, Any]] = {
    0: {"label": "Clear sky", "condition": "clear", "rainy": False, "icon": "☀️", "outdoor_suitable": True, "description": "Clear skies with plenty of sunshine."},
    1: {"label": "Mainly clear", "condition": "clear", "rainy": False, "icon": "🌤️", "outdoor_suitable": True, "description": "Mostly sunny with a few scattered clouds."},
    2: {"label": "Partly cloudy", "condition": "cloudy", "rainy": False, "icon": "⛅", "outdoor_suitable": True, "description": "Passing clouds with sunny intervals."},
    3: {"label": "Overcast", "condition": "cloudy", "rainy": False, "icon": "☁️", "outdoor_suitable": True, "description": "Cloudy skies throughout."},
    45: {"label": "Fog", "condition": "fog", "rainy": False, "icon": "🌫️", "outdoor_suitable": True, "description": "Foggy conditions reducing visibility."},
    48: {"label": "Depositing rime fog", "condition": "fog", "rainy": False, "icon": "🌫️", "outdoor_suitable": False, "description": "Dense freezing fog."},
    51: {"label": "Light drizzle", "condition": "rain", "rainy": True, "icon": "🌦️", "outdoor_suitable": False, "description": "Light, intermittent drizzle."},
    53: {"label": "Moderate drizzle", "condition": "rain", "rainy": True, "icon": "🌧️", "outdoor_suitable": False, "description": "Steady drizzle."},
    55: {"label": "Dense drizzle", "condition": "rain", "rainy": True, "icon": "🌧️", "outdoor_suitable": False, "description": "Heavy mist and dense drizzle."},
    56: {"label": "Light freezing drizzle", "condition": "rain", "rainy": True, "icon": "🌧️", "outdoor_suitable": False, "description": "Freezing drizzle causing slick surfaces."},
    57: {"label": "Dense freezing drizzle", "condition": "rain", "rainy": True, "icon": "🌧️", "outdoor_suitable": False, "description": "Heavy freezing drizzle."},
    61: {"label": "Slight rain", "condition": "rain", "rainy": True, "icon": "🌦️", "outdoor_suitable": False, "description": "Light rain showers."},
    63: {"label": "Moderate rain", "condition": "rain", "rainy": True, "icon": "🌧️", "outdoor_suitable": False, "description": "Steady moderate rain."},
    65: {"label": "Heavy rain", "condition": "rain", "rainy": True, "icon": "🌧️", "outdoor_suitable": False, "description": "Heavy rain downpour."},
    66: {"label": "Light freezing rain", "condition": "rain", "rainy": True, "icon": "🌧️", "outdoor_suitable": False, "description": "Freezing rain."},
    67: {"label": "Heavy freezing rain", "condition": "rain", "rainy": True, "icon": "🌧️", "outdoor_suitable": False, "description": "Heavy freezing rain."},
    71: {"label": "Slight snow fall", "condition": "snow", "rainy": False, "icon": "🌨️", "outdoor_suitable": False, "description": "Light snowfall."},
    73: {"label": "Moderate snow fall", "condition": "snow", "rainy": False, "icon": "❄️", "outdoor_suitable": False, "description": "Steady snowfall."},
    75: {"label": "Heavy snow fall", "condition": "snow", "rainy": False, "icon": "❄️", "outdoor_suitable": False, "description": "Heavy accumulating snow."},
    77: {"label": "Snow grains", "condition": "snow", "rainy": False, "icon": "🌨️", "outdoor_suitable": False, "description": "Fine snow grains."},
    80: {"label": "Slight rain showers", "condition": "rain", "rainy": True, "icon": "🌦️", "outdoor_suitable": False, "description": "Scattered brief rain showers."},
    81: {"label": "Moderate rain showers", "condition": "rain", "rainy": True, "icon": "🌧️", "outdoor_suitable": False, "description": "Frequent rain showers."},
    82: {"label": "Violent rain showers", "condition": "rain", "rainy": True, "icon": "⛈️", "outdoor_suitable": False, "description": "Torrential downpours."},
    85: {"label": "Slight snow showers", "condition": "snow", "rainy": False, "icon": "🌨️", "outdoor_suitable": False, "description": "Scattered snow flurries."},
    86: {"label": "Heavy snow showers", "condition": "snow", "rainy": False, "icon": "❄️", "outdoor_suitable": False, "description": "Intense snow showers."},
    95: {"label": "Thunderstorm", "condition": "thunderstorm", "rainy": True, "icon": "⚡", "outdoor_suitable": False, "description": "Active thunderstorm with lightning."},
    96: {"label": "Thunderstorm with slight hail", "condition": "thunderstorm", "rainy": True, "icon": "⛈️", "outdoor_suitable": False, "description": "Severe storm with hail."},
    99: {"label": "Thunderstorm with heavy hail", "condition": "thunderstorm", "rainy": True, "icon": "⛈️", "outdoor_suitable": False, "description": "Severe storm with heavy hail and strong winds."},
}

RAINY_CODES = {k for k, v in WMO_WEATHER_CODES.items() if v["rainy"]}


def get_wmo_info(code: int | None) -> dict[str, Any]:
    """Retrieve metadata and semantic labels for a given WMO weather code."""
    if code is None:
        return {
            "label": "Unknown",
            "condition": "unknown",
            "rainy": False,
            "icon": "❓",
            "outdoor_suitable": True,
            "description": "Weather conditions unknown.",
        }
    return WMO_WEATHER_CODES.get(
        int(code),
        {
            "label": f"Weather code {code}",
            "condition": "mixed",
            "rainy": int(code) in RAINY_CODES,
            "icon": "🌤️",
            "outdoor_suitable": True,
            "description": "Variable weather conditions.",
        },
    )


# ---------------------------------------------------------------------------
# Core Weather Fetch Functions
# ---------------------------------------------------------------------------


def fetch_current_weather(lat: float, lon: float, *, strict: bool = False) -> dict[str, Any]:
    """Fetch live conditions at coordinates from Open-Meteo."""
    lat, lon = resolve_tool_coords(lat, lon, tool="get_current_weather")
    key = f"weather_mcp:curr:{round(lat, 3)}:{round(lon, 3)}"
    try:
        cached = ttl_cache.get(key)
        if cached:
            return cached
    except Exception as exc:
        log.warning("weather cache read error: %s", exc)

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m"
    )
    try:
        with httpx.Client(timeout=OPEN_METEO_TIMEOUT_S, headers=HEADERS) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        current = data.get("current") or {}
        if not current or current.get("weather_code") is None:
            raise ValueError("Open-Meteo response carried no usable current block")

        code = int(current.get("weather_code") or 0)
        wmo = get_wmo_info(code)
        precip = float(current.get("precipitation") or 0.0)
        rainy = wmo["rainy"] or precip > 0.0

        temp_c = current.get("temperature_2m")
        feels_like = current.get("apparent_temperature")
        humidity = current.get("relative_humidity_2m")
        wind_kmh = current.get("wind_speed_10m")
        is_day = bool(current.get("is_day", 1))

        result = {
            "temperature_c": temp_c,
            "feels_like_c": feels_like,
            "humidity_pct": humidity,
            "precipitation_mm": precip,
            "wind_speed_kmh": wind_kmh,
            "is_day": is_day,
            "weather_code": code,
            "condition": wmo["condition"],
            "condition_label": wmo["label"],
            "description": wmo["description"],
            "icon": wmo["icon"],
            "rainy": rainy,
            "outdoor_suitable": wmo["outdoor_suitable"] and not rainy and (wind_kmh is None or wind_kmh < 35.0),
            "lat": lat,
            "lon": lon,
            "source": "open-meteo",
            "freshness": "live",
        }
        ttl_cache.set(key, result, ttl_seconds=15 * 60)
        return result
    except Exception as exc:
        log.warning("Open-Meteo current weather failed for (%s, %s): %s", lat, lon, exc)
        if strict:
            raise ProviderUnavailable(
                "open-meteo",
                "Open-Meteo weather is unavailable (timeout or HTTP failure).",
            ) from None
        return {
            "temperature_c": None,
            "feels_like_c": None,
            "humidity_pct": None,
            "precipitation_mm": None,
            "wind_speed_kmh": None,
            "is_day": True,
            "weather_code": None,
            "condition": "unknown",
            "condition_label": "Unknown",
            "description": "Weather data unavailable.",
            "icon": "❓",
            "rainy": None,
            "outdoor_suitable": True,
            "source": "unavailable",
            "freshness": "unknown",
            "error": "open-meteo unavailable",
            "indoor_recommended": True,
            "lat": lat,
            "lon": lon,
        }


def fetch_weather_forecast(lat: float, lon: float, days: int = 7, *, strict: bool = False) -> dict[str, Any]:
    """Fetch daily weather forecast for up to 14 days from Open-Meteo."""
    lat, lon = resolve_tool_coords(lat, lon, tool="get_weather_forecast")
    days = max(1, min(int(days or 7), 14))
    key = f"weather_mcp:daily:{round(lat, 3)}:{round(lon, 3)}:{days}"
    try:
        cached = ttl_cache.get(key)
        if cached:
            return cached
    except Exception as exc:
        log.warning("weather forecast cache read error: %s", exc)

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&forecast_days={days}"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max"
    )
    try:
        with httpx.Client(timeout=OPEN_METEO_TIMEOUT_S, headers=HEADERS) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        daily = data.get("daily") or {}
        times = daily.get("time") or []
        codes = daily.get("weather_code") or []
        t_max = daily.get("temperature_2m_max") or []
        t_min = daily.get("temperature_2m_min") or []
        precip = daily.get("precipitation_sum") or []
        precip_prob = daily.get("precipitation_probability_max") or []
        winds = daily.get("wind_speed_10m_max") or []

        forecast_list: list[dict[str, Any]] = []
        for i, dt in enumerate(times):
            code = codes[i] if i < len(codes) else None
            wmo = get_wmo_info(code)
            rain_chance = precip_prob[i] if i < len(precip_prob) else None
            rainy = wmo["rainy"] or ((rain_chance or 0) >= 50)
            forecast_list.append({
                "date": dt,
                "weather_code": code,
                "condition": wmo["condition"],
                "condition_label": wmo["label"],
                "icon": wmo["icon"],
                "temp_max_c": t_max[i] if i < len(t_max) else None,
                "temp_min_c": t_min[i] if i < len(t_min) else None,
                "precipitation_mm": precip[i] if i < len(precip) else None,
                "rain_probability_pct": rain_chance,
                "max_wind_kmh": winds[i] if i < len(winds) else None,
                "rainy": rainy,
                "outdoor_suitable": wmo["outdoor_suitable"] and not rainy,
            })

        result = {
            "lat": lat,
            "lon": lon,
            "forecast_days": len(forecast_list),
            "days": forecast_list,
            "source": "open-meteo",
        }
        ttl_cache.set(key, result, ttl_seconds=60 * 60)
        return result
    except Exception as exc:
        log.warning("Open-Meteo forecast failed for (%s, %s): %s", lat, lon, exc)
        if strict:
            raise ProviderUnavailable("open-meteo", "Weather forecast unavailable.") from None
        return {"lat": lat, "lon": lon, "forecast_days": 0, "days": [], "error": str(exc), "source": "unavailable"}


def fetch_hourly_forecast(lat: float, lon: float, hours: int = 24, *, strict: bool = False) -> dict[str, Any]:
    """Fetch next N hours of hourly forecast from Open-Meteo."""
    lat, lon = resolve_tool_coords(lat, lon, tool="get_hourly_forecast")
    hours = max(1, min(int(hours or 24), 72))
    key = f"weather_mcp:hourly:{round(lat, 3)}:{round(lon, 3)}:{hours}"
    try:
        cached = ttl_cache.get(key)
        if cached:
            return cached
    except Exception as exc:
        log.warning("weather hourly cache read error: %s", exc)

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&forecast_days=3"
        "&hourly=temperature_2m,precipitation_probability,weather_code,wind_speed_10m"
    )
    try:
        with httpx.Client(timeout=OPEN_METEO_TIMEOUT_S, headers=HEADERS) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        hourly = data.get("hourly") or {}
        times = (hourly.get("time") or [])[:hours]
        temps = (hourly.get("temperature_2m") or [])[:hours]
        probs = (hourly.get("precipitation_probability") or [])[:hours]
        codes = (hourly.get("weather_code") or [])[:hours]
        winds = (hourly.get("wind_speed_10m") or [])[:hours]

        hours_list: list[dict[str, Any]] = []
        for i, dt in enumerate(times):
            code = codes[i] if i < len(codes) else None
            wmo = get_wmo_info(code)
            rain_prob = probs[i] if i < len(probs) else 0
            hours_list.append({
                "time": dt,
                "temperature_c": temps[i] if i < len(temps) else None,
                "rain_probability_pct": rain_prob,
                "weather_code": code,
                "condition": wmo["condition"],
                "condition_label": wmo["label"],
                "icon": wmo["icon"],
                "wind_speed_kmh": winds[i] if i < len(winds) else None,
                "rainy": wmo["rainy"] or ((rain_prob or 0) >= 50),
            })

        result = {
            "lat": lat,
            "lon": lon,
            "hours_count": len(hours_list),
            "hours": hours_list,
            "source": "open-meteo",
        }
        ttl_cache.set(key, result, ttl_seconds=30 * 60)
        return result
    except Exception as exc:
        log.warning("Open-Meteo hourly failed for (%s, %s): %s", lat, lon, exc)
        if strict:
            raise ProviderUnavailable("open-meteo", "Hourly weather forecast unavailable.") from None
        return {"lat": lat, "lon": lon, "hours_count": 0, "hours": [], "error": str(exc), "source": "unavailable"}


def fetch_weather_by_city(city: str, country: str | None = None, *, strict: bool = False) -> dict[str, Any]:
    """Geocode a city name and fetch its live weather and short forecast."""
    city_q = (city or "").strip()
    if not city_q:
        raise ValueError("City name is required")

    geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city_q}&count=1&language=en&format=json"
    lat, lon, resolved_city, resolved_country = None, None, city_q, ""
    try:
        with httpx.Client(timeout=8.0, headers=HEADERS) as client:
            resp = client.get(geo_url)
            if resp.status_code == 200:
                results = resp.json().get("results") or []
                if results:
                    top = results[0]
                    lat = float(top.get("latitude"))
                    lon = float(top.get("longitude"))
                    resolved_city = top.get("name") or city_q
                    resolved_country = top.get("country") or ""
    except Exception as exc:
        log.warning("Geocoding failed for %s: %s", city_q, exc)

    if lat is None or lon is None:
        # Fallback to local Nominatim reverse/search if available
        from moodos.config import settings

        try:
            with httpx.Client(timeout=8.0, headers=HEADERS) as client:
                r = client.get(f"{settings.nominatim_url.rstrip('/')}/search", params={"q": city_q, "format": "jsonv2", "limit": 1})
                items = r.json()
                if items:
                    lat = float(items[0]["lat"])
                    lon = float(items[0]["lon"])
                    resolved_city = items[0].get("name") or city_q
        except Exception:
            pass

    if lat is None or lon is None:
        if strict:
            raise ProviderUnavailable("geocoding", f"Could not find coordinates for city: {city_q}")
        return {"city": city_q, "found": False, "error": f"City '{city_q}' not found."}

    current = fetch_current_weather(lat, lon, strict=strict)
    forecast = fetch_weather_forecast(lat, lon, days=3, strict=False)

    return {
        "city": resolved_city,
        "country": resolved_country,
        "lat": lat,
        "lon": lon,
        "found": True,
        "current": current,
        "upcoming_days": forecast.get("days", []),
    }


def evaluate_weather_for_activity(
    lat: float, lon: float, activity: str = "outdoor_walk", *, strict: bool = False
) -> dict[str, Any]:
    """Evaluate weather conditions for an intended activity (outdoor dining, walking, etc.)."""
    weather = fetch_current_weather(lat, lon, strict=strict)
    act = (activity or "outdoor_walk").lower().replace(" ", "_")

    temp = weather.get("temperature_c") or 22.0
    rainy = bool(weather.get("rainy"))
    wind = weather.get("wind_speed_kmh") or 10.0
    condition = weather.get("condition", "clear")

    is_suitable = True
    score = 1.0
    reasons: list[str] = []

    if "indoor" in act or "cinema" in act or "museum" in act or "theater" in act:
        return {
            "activity": activity,
            "suitable": True,
            "suitability_score": 1.0,
            "recommendation": "Ideal for current weather — comfortable indoor venue.",
            "indoor_recommended": False,
            "weather_summary": weather,
        }

    if rainy:
        is_suitable = False
        score -= 0.7
        reasons.append("Rain or precipitation detected.")

    if wind >= 30.0:
        score -= 0.3
        reasons.append(f"High wind speeds ({wind} km/h).")

    if temp > 38.0:
        score -= 0.4
        reasons.append(f"Very hot weather ({temp}°C).")
        if "walk" in act or "outdoor" in act:
            is_suitable = False
    elif temp < 8.0:
        score -= 0.3
        reasons.append(f"Chilly temperatures ({temp}°C).")

    score = max(0.0, min(round(score, 2), 1.0))
    if not is_suitable:
        recommendation = f"Conditions are unfavorable for {activity} due to: {', '.join(reasons)}. Indoor alternatives recommended."
    elif score < 0.7:
        recommendation = f"Acceptable conditions for {activity}, but note: {', '.join(reasons) or 'moderate conditions'}."
    else:
        recommendation = f"Great weather for {activity}! Enjoy the {condition} conditions ({temp}°C)."

    return {
        "activity": activity,
        "suitable": is_suitable,
        "suitability_score": score,
        "recommendation": recommendation,
        "indoor_recommended": not is_suitable,
        "reasons": reasons,
        "weather_summary": {
            "temperature_c": temp,
            "condition": condition,
            "condition_label": weather.get("condition_label"),
            "rainy": rainy,
            "wind_speed_kmh": wind,
        },
    }


# ---------------------------------------------------------------------------
# Open-Meteo Weather MCP Server
# ---------------------------------------------------------------------------


class OpenMeteoWeatherMCPServer:
    """Standard Model Context Protocol (MCP) Server for Open-Meteo Weather.

    Features:
    - MCP Tool Registry with JSON Schema definitions
    - JSON-RPC 2.0 message handler compatible with MCP specification
    - Rich weather tools: current, forecast, hourly, city lookup, and activity fit
    """

    def __init__(self) -> None:
        self.name = "open-meteo-weather-mcp"
        self.version = "1.0.0"
        self.tools: dict[str, Callable[..., Any]] = {
            "get_current_weather": self.get_current_weather,
            "get_weather_forecast": self.get_weather_forecast,
            "get_hourly_forecast": self.get_hourly_forecast,
            "get_weather_by_city": self.get_weather_by_city,
            "evaluate_weather_for_activity": self.evaluate_weather_for_activity,
        }

    # Tool Implementations
    def tool(self, name: str | None = None, description: str | None = None) -> Callable:
        """Decorator to register a weather tool on the Weather MCP server:

        @weather_mcp_server.tool()
        def custom_weather_tool(lat: float, lon: float) -> dict:
            ...
        """
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or fn.__name__
            if description and not fn.__doc__:
                fn.__doc__ = description
            self.tools[tool_name] = fn
            return fn
        return decorator

    def get_current_weather(self, lat: float, lon: float) -> dict[str, Any]:
        """Get live current weather conditions at latitude and longitude coordinates."""
        return fetch_current_weather(lat, lon, strict=True)

    def get_weather_forecast(self, lat: float, lon: float, days: int = 7) -> dict[str, Any]:
        """Get multi-day daily weather forecast with temperatures and rain probabilities."""
        return fetch_weather_forecast(lat, lon, days=days, strict=True)

    def get_hourly_forecast(self, lat: float, lon: float, hours: int = 24) -> dict[str, Any]:
        """Get hour-by-hour weather forecast breakdown for the next N hours."""
        return fetch_hourly_forecast(lat, lon, hours=hours, strict=True)

    def get_weather_by_city(self, city: str, country: str | None = None) -> dict[str, Any]:
        """Look up weather for a given city name with automatic geocoding."""
        return fetch_weather_by_city(city, country=country, strict=True)

    def evaluate_weather_for_activity(self, lat: float, lon: float, activity: str = "outdoor_walk") -> dict[str, Any]:
        """Evaluate if current weather is suitable for an activity (e.g. walk, dining, cinema)."""
        return evaluate_weather_for_activity(lat, lon, activity=activity, strict=True)

    # Schema Generation
    def tool_schema(self, name: str) -> dict[str, Any]:
        """Generate MCP JSON Schema for a given tool name."""
        schemas: dict[str, dict[str, Any]] = {
            "get_current_weather": {
                "name": "get_current_weather",
                "description": "Fetch real-time weather conditions (temperature, rain, wind, condition) for a location.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "Latitude coordinate (-90 to 90)"},
                        "lon": {"type": "number", "description": "Longitude coordinate (-180 to 180)"},
                    },
                    "required": ["lat", "lon"],
                },
            },
            "get_weather_forecast": {
                "name": "get_weather_forecast",
                "description": "Fetch multi-day daily weather forecast (highs/lows, precipitation chance) for a location.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "Latitude coordinate (-90 to 90)"},
                        "lon": {"type": "number", "description": "Longitude coordinate (-180 to 180)"},
                        "days": {"type": "integer", "description": "Number of forecast days (1 to 14)", "default": 7},
                    },
                    "required": ["lat", "lon"],
                },
            },
            "get_hourly_forecast": {
                "name": "get_hourly_forecast",
                "description": "Fetch hourly weather forecast for scheduling and activities over the next 24 to 72 hours.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "Latitude coordinate (-90 to 90)"},
                        "lon": {"type": "number", "description": "Longitude coordinate (-180 to 180)"},
                        "hours": {"type": "integer", "description": "Number of hours ahead (1 to 72)", "default": 24},
                    },
                    "required": ["lat", "lon"],
                },
            },
            "get_weather_by_city": {
                "name": "get_weather_by_city",
                "description": "Look up weather conditions and 3-day forecast by city name.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name (e.g., 'Ahmedabad', 'New Delhi', 'London')"},
                        "country": {"type": "string", "description": "Optional country code or name filter"},
                    },
                    "required": ["city"],
                },
            },
            "evaluate_weather_for_activity": {
                "name": "evaluate_weather_for_activity",
                "description": "Assess weather suitability for an intended outdoor or indoor activity.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "Latitude coordinate (-90 to 90)"},
                        "lon": {"type": "number", "description": "Longitude coordinate (-180 to 180)"},
                        "activity": {
                            "type": "string",
                            "description": "Activity type (e.g. 'outdoor_walk', 'outdoor_dining', 'park', 'cinema', 'sightseeing')",
                            "default": "outdoor_walk",
                        },
                    },
                    "required": ["lat", "lon"],
                },
            },
        }
        if name not in schemas:
            raise KeyError(f"Unknown weather MCP tool: {name}")
        return schemas[name]

    def list_tools(self) -> list[dict[str, Any]]:
        """List all tools with their MCP schema."""
        return [self.tool_schema(name) for name in sorted(self.tools.keys())]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Invoke an MCP tool by name with arguments."""
        if name not in self.tools:
            raise KeyError(f"Unknown tool: '{name}'. Available: {list(self.tools.keys())}")
        args = arguments or {}
        from moodos.terminal_stream import terminal_bus
        args_str = terminal_bus.format_args(args)
        terminal_bus.log_tool_call(f"weather_mcp:{name}", args_str)
        t0 = time.perf_counter()
        try:
            res = self.tools[name](**args)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            summary = terminal_bus.format_result(name, res)
            terminal_bus.log_tool_result(f"weather_mcp:{name}", elapsed_ms, summary)
            return res
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            terminal_bus.log_tool_result(f"weather_mcp:{name}", elapsed_ms, str(exc), is_error=True)
            raise

    def handle_jsonrpc(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle standard JSON-RPC 2.0 MCP messages."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": self.name, "version": self.version},
                    "capabilities": {"tools": {"listChanged": False}},
                },
            }
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.list_tools()},
            }
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments") or {}
            try:
                result = self.call_tool(tool_name, tool_args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                        "isError": False,
                    },
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error executing tool '{tool_name}': {exc}"}],
                        "isError": True,
                    },
                }
        elif method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method '{method}' not found"},
            }


# ---------------------------------------------------------------------------
# Open-Meteo Weather MCP Client
# ---------------------------------------------------------------------------


class OpenMeteoWeatherMCPClient:
    """MCP Client for connecting to and consuming the Weather MCP Server.

    Supports both in-process bound dispatch and HTTP JSON-RPC dispatch.
    """

    def __init__(self, server: OpenMeteoWeatherMCPServer | None = None, server_url: str | None = None) -> None:
        self.server = server or OpenMeteoWeatherMCPServer()
        self.server_url = server_url

    def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the Weather MCP server."""
        if self.server_url:
            resp = httpx.post(self.server_url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=10.0)
            return resp.json().get("result", {}).get("tools", [])
        return self.server.list_tools()

    def call_tool(self, name: str, **kwargs: Any) -> Any:
        """Call a weather tool on the server with keyword arguments."""
        if self.server_url:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": kwargs},
            }
            resp = httpx.post(self.server_url, json=payload, timeout=OPEN_METEO_TIMEOUT_S)
            data = resp.json().get("result", {})
            if data.get("isError"):
                content = data.get("content", [{}])[0].get("text", "Unknown error")
                raise RuntimeError(content)
            raw_text = data.get("content", [{}])[0].get("text", "{}")
            return json.loads(raw_text)
        return self.server.call_tool(name, kwargs)

    # Convenience helper methods
    def get_current_weather(self, lat: float, lon: float) -> dict[str, Any]:
        return self.call_tool("get_current_weather", lat=lat, lon=lon)

    def get_forecast(self, lat: float, lon: float, days: int = 7) -> dict[str, Any]:
        return self.call_tool("get_weather_forecast", lat=lat, lon=lon, days=days)

    def get_hourly(self, lat: float, lon: float, hours: int = 24) -> dict[str, Any]:
        return self.call_tool("get_hourly_forecast", lat=lat, lon=lon, hours=hours)

    def get_by_city(self, city: str, country: str | None = None) -> dict[str, Any]:
        return self.call_tool("get_weather_by_city", city=city, country=country)

    def evaluate_activity(self, lat: float, lon: float, activity: str = "outdoor_walk") -> dict[str, Any]:
        return self.call_tool("evaluate_weather_for_activity", lat=lat, lon=lon, activity=activity)


# Singletons for application-wide use
weather_mcp_server = OpenMeteoWeatherMCPServer()
weather_mcp_client = OpenMeteoWeatherMCPClient(server=weather_mcp_server)
