from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from moodos import providers

_EST_TIMES = ("17:50", "18:40", "19:15", "20:00", "21:10")
_EST_PRICES = (220, 230, 250, 260, 240)


def list_showtimes(
    lat: float | None = None,
    lon: float | None = None,
    limit: int = 4,
    region: str = "IN",
    movies: list[dict] | None = None,
) -> list[dict]:
    """Pair live TMDB now-playing titles with estimated evening times.

    There is no free India box-office / BMS feed, so times and prices are
    explicitly marked as estimates. Cinema names and coordinates come from the
    caller (real OSM venues), not a canned Ahmedabad list.
    """
    films = movies if movies is not None else providers.tmdb_now_playing(region=region, limit=limit)
    shows: list[dict] = []
    for i, film in enumerate(films[:limit]):
        title = film.get("title")
        if not title:
            continue
        shows.append(
            {
                "provider": "TMDB now playing",
                "cinema": None,
                "lat": lat,
                "lon": lon,
                "movie": title,
                "tmdb_id": film.get("tmdb_id"),
                "overview": (film.get("text") or "")[:240],
                "poster_url": film.get("poster_url"),
                "original_language": film.get("original_language"),
                "release_date": film.get("release_date"),
                "time": _EST_TIMES[i % len(_EST_TIMES)],
                "price_inr": _EST_PRICES[i % len(_EST_PRICES)],
                "seats": "check at venue",
                "showtime_estimated": True,
                "source": film.get("source") or "tmdb-now-playing",
            }
        )
    return shows


def prepare_movie_booking(show_index: int = 0, show: dict | None = None) -> dict[str, Any]:
    live = show or (list_showtimes(limit=max(show_index + 1, 1)) or [None])[min(show_index, 0)]
    if not live:
        shows = list_showtimes(limit=4)
        live = shows[show_index % len(shows)] if shows else {
            "movie": "Tonight's screening",
            "time": "19:15",
            "price_inr": 220,
            "showtime_estimated": True,
            "provider": "TMDB now playing",
        }
    return {
        "status": "prepared",
        "requires_confirmation": True,
        "show": live,
        "expires_at": (datetime.now() + timedelta(minutes=8)).isoformat(timespec="seconds"),
        "note": "No money is charged. Showtime is an estimate — confirm at the cinema. This is not a live ticket purchase.",
    }


def confirm_movie_booking(confirmed: bool, show: dict | None = None) -> dict[str, Any]:
    if not confirmed:
        return {"status": "aborted", "executed": False}
    return {
        "status": "recorded",
        "executed": True,
        "provider": "MoodOS (no live ticketing — confirm at the cinema)",
        "show": show or {},
        "confirmation_code": f"MOODOS-{datetime.now().strftime('%H%M%S')}",
    }


def prepare_food_order(item: dict) -> dict[str, Any]:
    return {
        "status": "prepared",
        "requires_confirmation": True,
        "item": item,
        "provider": "FoodOrderingProvider (no live order)",
    }
