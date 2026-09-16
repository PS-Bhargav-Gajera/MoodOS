"""Location Resolver: fuse browser GPS, user-entered location, and IP location
into one best-guess "where am I" with a confidence score, then reverse-geocode
it to a readable city/area/state label.

Sources are ranked by confidence:
  1. User-entered location  (explicit, highest trust)   -> geocoded
  2. Browser GPS             (accurate but can be stale/wrong) -> reverse geocoded
  3. IP location             (city-level, low accuracy)  -> reverse geocoded
"""

from __future__ import annotations

import httpx
from typing import Any

from moodos.config import settings
from moodos.providers import HEADERS, TIMEOUT, reverse_geocode

IP_SERVICE_URL = "http://ip-api.com/json/{ip}?fields=status,message,lat,lon,city,regionName,country"


def geocode_text(text: str) -> dict[str, Any] | None:
    """Forward-geocode a free-text 'city/area' into coords + names via Nominatim."""
    if not text or not text.strip():
        return None
    params = {"q": text.strip(), "format": "jsonv2", "limit": 1, "addressdetails": 1}
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
            rows = client.get("https://nominatim.openstreetmap.org/search", params=params).json()
    except Exception:
        return None
    if not rows:
        return None
    top = rows[0]
    addr = top.get("address") or {}
    cc = (addr.get("country_code") or "").lower()
    city = (
        addr.get("city") or addr.get("town")
        or addr.get("state_district") or addr.get("county")
        or addr.get("municipality") or addr.get("village")
    )
    suburb = addr.get("suburb") or addr.get("neighbourhood")
    village = addr.get("village")
    area = ", ".join(
        p for p in (
            addr.get("suburb"),
            village if village and village != city else None,
            addr.get("neighbourhood"),
        ) if p
    ).strip()
    return {
        "lat": float(top.get("lat") or 0),
        "lon": float(top.get("lon") or 0),
        "city": city,
        "area": area,
        "state": addr.get("state"),
        "country": addr.get("country"),
        "display_name": top.get("display_name"),
        "matched": top.get("display_name"),
    }


def ip_location(ip: str | None = None) -> dict[str, Any] | None:
    """City-level location from the client IP via ip-api.com (free, no key)."""
    target = ip or "json"
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
            data = client.get(IP_SERVICE_URL.format(ip=target)).json()
    except Exception:
        return None
    if data.get("status") != "success":
        return None
    return {
        "lat": float(data.get("lat") or 0),
        "lon": float(data.get("lon") or 0),
        "city": data.get("city"),
        "area": "",
        "state": data.get("regionName"),
        "country": data.get("country"),
    }


def resolve_location(
    lat: float | None = None,
    lon: float | None = None,
    user_label: str | None = None,
    ip: str | None = None,
) -> dict[str, Any]:
    """Pick the most confident location source and reverse-geocode it.

    Returns a normalized dict with coords, names, source, and confidence.
    Falls back to the configured default city only if everything fails.
    """
    candidates: list[dict[str, Any]] = []

    if user_label and user_label.strip():
        geo = geocode_text(user_label)
        if geo and geo.get("lat") and geo.get("lon"):
            candidates.append(
                {"lat": geo["lat"], "lon": geo["lon"], "source": "user",
                 "confidence": 0.98, "label": user_label.strip()}
            )

    if lat is not None and lon is not None:
        candidates.append(
            {"lat": float(lat), "lon": float(lon), "source": "gps",
             "confidence": 0.82, "label": "browser GPS"}
        )

    ip_res = ip_location(ip) if ip else None
    if ip_res and ip_res.get("lat") and ip_res.get("lon"):
        candidates.append(
            {"lat": ip_res["lat"], "lon": ip_res["lon"], "source": "ip",
             "confidence": 0.45, "label": "IP location" + (f" ({ip_res.get('city')})" if ip_res.get("city") else "")}
        )

    if not candidates:
        # Everything failed: use configured default with lowest confidence.
        return {
            "lat": settings.default_lat,
            "lon": settings.default_lon,
            "source": "default",
            "confidence": 0.1,
            "label": "default city",
            "gps_live": False,
            "user_override": False,
            "city": settings.default_city,
            "area": "",
            "state": "",
        }

    best = max(candidates, key=lambda c: c["confidence"])
    resolved = reverse_geocode(best["lat"], best["lon"])
    return {
        "lat": best["lat"],
        "lon": best["lon"],
        "source": best["source"],
        "confidence": best["confidence"],
        "label": best["label"],
        "gps_live": best["source"] == "gps",
        "user_override": best["source"] == "user",
        "city": resolved.get("city") or best.get("label"),
        "area": resolved.get("area") or "",
        "state": resolved.get("state") or "",
        "country": resolved.get("country") or "",
        "display_name": resolved.get("display_name"),
    }
