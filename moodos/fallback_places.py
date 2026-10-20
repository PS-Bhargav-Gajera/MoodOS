"""P1a: fallback POI lookup when Overpass is down.

NOT wired into any tool yet (per PROGRESS.md P1a). Exposes:

    fallback_places(lat, lon, category, limit=10) -> list[dict]

Returns the SAME dict shape as location_service.search_nearby_places
(keys copied from location_service._build_place). category is one of:
restaurant, cafe, cinema, park (park maps to the Overpass "walk" spec,
which is what search_nearby_places returns for parks).

Provider selection reads only KEY NAMES from .env / the environment —
never values are logged or hardcoded:
  * GEOAPIFY_API_KEY  -> Geoapify Places API
  * FOURSQUARE_API_KEY -> Foursquare Places API (v3)
  * otherwise -> Nominatim /search (viewbox around lat/lon, bounded=1,
    max 1 request per second, project User-Agent from providers.HEADERS).

Every result's ``source`` field names the provider actually used.
No static lists: every row comes from the provider response.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from moodos.config import settings
from moodos.nlu import haversine_km
from moodos.providers import HEADERS, TIMEOUT, _estimate_food_cost

log = logging.getLogger("moodos.fallback_places")

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# Mirrors of the location_service._CATEGORY_SPECS entries for the four
# supported inputs (values copied from that file, not invented). "park"
# maps to spec name "walk" — the same value search_nearby_places emits
# for leisure=park.
_SPECS: dict[str, dict[str, Any]] = {
    "cafe": {"name": "cafe", "subtype": "cafe", "kind": "place",
             "duration_min": 45, "dwell_family": "food"},
    "restaurant": {"name": "restaurant", "subtype": "restaurant", "kind": "food",
                   "duration_min": 60, "dwell_family": "food"},
    "cinema": {"name": "cinema", "subtype": "cinema", "kind": "place",
               "duration_min": 30, "has_venue": True, "dwell_family": "venue"},
    "park": {"name": "walk", "subtype": "walk", "kind": "place",
             "duration_min": 30, "outdoor": True, "needs_clear_weather": True,
             "dwell_family": "outdoor"},
}

# One request per second across this module (public Nominatim policy).
_MIN_INTERVAL_S = 1.0
_THROTTLE_LOCK = threading.Lock()
_LAST_CALL = 0.0

# viewbox half-width in degrees (~2.2 km at Delhi's latitude)
_VIEWBOX_DELTA = 0.02


def _env_key_names() -> set[str]:
    """Key NAMES only, from .env + the process environment. Values never read."""
    names: set[str] = set(os.environ)
    try:
        if _ENV_PATH.exists():
            for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    names.add(line.split("=", 1)[0].strip())
    except OSError:
        pass
    return names


def _env_value(name: str) -> str | None:
    """Look up a single env var for the chosen provider (value never logged)."""
    v = (os.environ.get(name) or "").strip()
    if v:
        return v
    try:
        if _ENV_PATH.exists():
            for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _throttle() -> None:
    global _LAST_CALL
    with _THROTTLE_LOCK:
        now = time.monotonic()
        wait = _MIN_INTERVAL_S - (now - _LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL = time.monotonic()


def _to_place(row: dict[str, Any], spec: dict[str, Any], provider: str,
              lat: float, lon: float) -> dict[str, Any]:
    """Build one normalized place — keys copied from location_service._build_place."""
    plat = row.get("lat")
    plon = row.get("lon")
    dist = round(haversine_km(lat, lon, plat, plon), 2) if (plat and plon) else None
    family = spec.get("dwell_family", "venue")
    if family == "food":
        cost, tier = _estimate_food_cost({}, row.get("name") or "", spec.get("subtype", "restaurant"))
        price_est = True
    else:
        cost, tier, price_est = 0, None, False
    return {
        # normalized identity
        "id": f"{provider}:{row.get('source_id')}",
        "source_id": row.get("source_id"),
        "name": row.get("name"),
        "title": row.get("name"),
        "category": spec.get("name"),
        "subtype": spec.get("subtype"),
        "kind": spec.get("kind"),
        "lat": plat,
        "lon": plon,
        "source": provider,
        # real-world facts (None = genuinely unknown, never invented)
        "address": row.get("address"),
        "phone": None,
        "website": None,
        "opening_hours": None,
        "opening_note": "",
        "likely_closed_at": None,
        "cuisine": None,
        "price_level": None,
        "price_tier": tier,
        "price_is_estimate": price_est,
        "rating": None,
        # distance + times (haversine estimate only)
        "distance_km": dist,
        "distance_label": _fmt_km(dist),
        "walk_min": _walk_est(dist),
        "drive_min": _drive_est(dist),
        "routing_source": "estimate",
        # ranker/planner contract
        "estimated_cost": cost,
        "duration_min": int(spec.get("duration_min") or 45),
        "intensity": "low",
        "crowded": False,
        "outdoor": bool(spec.get("outdoor")),
        "needs_clear_weather": bool(spec.get("needs_clear_weather")),
        "has_venue": bool(spec.get("has_venue")) or family in {"food", "venue"},
        "review_quality": 7.0,
        "moods": _moods_for(spec.get("name")),
        "text": f"{row.get('name')} — {spec.get('name')}",
    }


# Identical to the private helpers in location_service (imported lazily to
# avoid a module-level import cycle; same values, same rounding).
def _fmt_km(km: float | None) -> str | None:
    if km is None:
        return None
    return f"{km:.1f} km" if km < 10 else f"{int(round(km))} km"


def _walk_est(km: float | None) -> int | None:
    if km is None:
        return None
    return max(4, int(round(km * 12)))


def _drive_est(km: float | None) -> int | None:
    if km is None:
        return None
    return max(4, int(round(km * 1.6 + 2)))


def _moods_for(category: str) -> list[str]:
    return {
        "cafe": ["calm", "relaxed"], "restaurant": ["happy", "content"],
        "walk": ["calm", "refreshed"], "cinema": ["calm", "warm"],
    }.get(category or "", [])


def _nominatim_search(lat: float, lon: float, q: str, limit: int) -> list[dict[str, Any]]:
    left, right = lon - _VIEWBOX_DELTA, lon + _VIEWBOX_DELTA
    bottom, top = lat - _VIEWBOX_DELTA, lat + _VIEWBOX_DELTA
    params = {
        "q": q,
        "format": "jsonv2",
        "limit": limit,
        "viewbox": f"{left},{top},{right},{bottom}",
        "bounded": 1,
    }
    _throttle()
    url = settings.nominatim_url.rstrip("/") + "/search"
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        rows = resp.json()
    out: list[dict[str, Any]] = []
    for r in rows[:limit]:
        name = (r.get("name") or (r.get("display_name") or "").split(",")[0] or "").strip()
        if not name:
            continue  # unnamed row — no usable place data
        try:
            plat, plon = float(r["lat"]), float(r["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"source_id": str(r.get("place_id")), "name": name,
                    "lat": plat, "lon": plon, "address": r.get("display_name")})
    return out


def _geoapify_search(lat: float, lon: float, q: str, limit: int) -> list[dict[str, Any]]:
    key = _env_value("GEOAPIFY_API_KEY")
    if not key:
        return []
    params = {
        "filter": f"circle:{lon},{lat},2000",
        "bias": f"proximity:{lon},{lat}",
        "limit": limit,
        "lang": "en",
        "categories": {"restaurant": "restaurant", "cafe": "cafe",
                       "cinema": "cinema", "park": "park"}.get(q, q),
        "apiKey": key,
    }
    _throttle()
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
        resp = client.get("https://api.geoapify.com/v1/places", params=params)
        resp.raise_for_status()
        feats = (resp.json() or {}).get("features") or []
    out: list[dict[str, Any]] = []
    for f in feats[:limit]:
        p = f.get("properties") or {}
        geo = f.get("geometry") or {}
        coords = geo.get("coordinates") or []
        name = (p.get("name") or (p.get("formatted") or "").split(",")[0] or "").strip()
        if not name or len(coords) < 2:
            continue
        out.append({"source_id": str(p.get("place_id") or (p.get("datasource") or {}).get("raw", {}).get("osm_id", "")),
                    "name": name, "lat": float(coords[1]), "lon": float(coords[0]),
                    "address": p.get("formatted")})
    return out


def _foursquare_search(lat: float, lon: float, q: str, limit: int) -> list[dict[str, Any]]:
    key = _env_value("FOURSQUARE_API_KEY")
    if not key:
        return []
    headers = {**HEADERS, "Authorization": key, "Accept": "application/json"}
    params = {"ll": f"{lat},{lon}", "radius": 2000, "limit": limit, "query": q}
    _throttle()
    with httpx.Client(timeout=TIMEOUT, headers=headers) as client:
        resp = client.get("https://api.foursquare.com/v3/places/search", params=params)
        resp.raise_for_status()
        rows = resp.json() or []
    out: list[dict[str, Any]] = []
    for r in rows[:limit]:
        loc = r.get("location") or {}
        name = (r.get("name") or "").strip()
        try:
            plat, plon = float(loc["lat"]), float(loc["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        if not name:
            continue
        out.append({"source_id": str(r.get("fsq_id")), "name": name,
                    "lat": plat, "lon": plon, "address": loc.get("formatted_address")})
    return out


def fallback_places(lat: float, lon: float, category: str, limit: int = 10) -> list[dict[str, Any]]:
    """Nearby POIs from Geoapify/Foursquare if keyed, else Nominatim.

    Same output shape as location_service.search_nearby_places. Never raises:
    provider failure returns an honest empty list.
    """
    cat = (category or "").strip().lower()
    spec = _SPECS.get(cat)
    if spec is None:
        log.warning("fallback_places: unsupported category %r", category)
        return []
    limit = max(1, min(int(limit or 10), 25))

    keys = _env_key_names()
    try:
        if "GEOAPIFY_API_KEY" in keys:
            provider, rows = "geoapify", _geoapify_search(lat, lon, cat, limit)
        elif "FOURSQUARE_API_KEY" in keys:
            provider, rows = "foursquare", _foursquare_search(lat, lon, cat, limit)
        else:
            provider, rows = "nominatim", _nominatim_search(lat, lon, cat, limit)
    except Exception as exc:  # noqa: BLE001 - fallback must never raise
        log.warning("fallback_places %s failed: %s", cat, exc)
        return []

    places = [_to_place(r, spec, provider, lat, lon) for r in rows[:limit]]
    places.sort(key=lambda p: (p.get("distance_km") or 999.0))
    return places[:limit]
