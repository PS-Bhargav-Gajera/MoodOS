from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

CINEMA_SHOWS = [
    {
        "provider": "MockProvider",
        "cinema": "PVR Acropolis, Ahmedabad",
        "lat": 23.0225,
        "lon": 72.5419,
        "movie": "The Lunchbox",
        "time": "19:15",
        "price_inr": 220,
        "seats": "available",
    },
    {
        "provider": "MockProvider",
        "cinema": "Cinepolis Alpha One, Ahmedabad",
        "lat": 23.0377,
        "lon": 72.5389,
        "movie": "Paddington in Peru",
        "time": "18:40",
        "price_inr": 250,
        "seats": "available",
    },
    {
        "provider": "MockProvider",
        "cinema": "PVR Mutiplex Motera, Ahmedabad",
        "lat": 23.1047,
        "lon": 72.5961,
        "movie": "Everything Everywhere All at Once",
        "time": "20:00",
        "price_inr": 260,
        "seats": "available",
    },
    {
        "provider": "MockProvider",
        "cinema": "INOX Iscon Mall, Ahmedabad",
        "lat": 23.0307,
        "lon": 72.5080,
        "movie": "Little Miss Sunshine",
        "time": "17:50",
        "price_inr": 230,
        "seats": "available",
    },
]

MUSIC_PLAYLIST_NAMES = [
    "MoodOS — calm acoustic evening",
    "MoodOS — soft indie evening",
    "MoodOS — lo-fi focus moments",
    "MoodOS — gentle chill morning",
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def list_showtimes(
    lat: float | None = None, lon: float | None = None, limit: int = 4
) -> list[dict]:
    """Live-shaped data from CinemaBookingProvider mock — not a public BMS scrape.

    When lat/lon are provided, shows are sorted by the driving distance from the
    user to the nearest venue (nearest first).
    """
    shows = list(CINEMA_SHOWS)
    if lat is not None and lon is not None:
        def key(s: dict) -> float:
            try:
                return _haversine_km(lat, lon, float(s["lat"]), float(s["lon"]))
            except (TypeError, ValueError, KeyError):
                return 9999.0

        shows.sort(key=key)
    return shows[:limit]


def prepare_movie_booking(show_index: int = 0) -> dict[str, Any]:
    show = CINEMA_SHOWS[show_index % len(CINEMA_SHOWS)]
    return {
        "status": "prepared",
        "requires_confirmation": True,
        "show": show,
        "expires_at": (datetime.now() + timedelta(minutes=8)).isoformat(timespec="seconds"),
        "note": "No money is charged until confirm_movie_booking after explicit user confirmation.",
    }


def confirm_movie_booking(confirmed: bool, show: dict | None = None) -> dict[str, Any]:
    if not confirmed:
        return {"status": "aborted", "executed": False}
    return {
        "status": "executed_mock",
        "executed": True,
        "provider": "CinemaBookingProvider.MockProvider",
        "show": show or CINEMA_SHOWS[0],
        "confirmation_code": "MOODOS-MOCK-4821",
    }


def prepare_food_order(item: dict) -> dict[str, Any]:
    return {
        "status": "prepared",
        "requires_confirmation": True,
        "item": item,
        "provider": "FoodOrderingProvider.MockProvider",
    }
