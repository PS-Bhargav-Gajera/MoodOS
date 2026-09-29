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

IP_FIELDS = "status,message,lat,lon,city,regionName,country,countryCode"


def _nominatim_search_url() -> str:
    return f"{settings.nominatim_url.rstrip('/')}/search"


def geocode_text(text: str) -> dict[str, Any] | None:
    """Forward-geocode a free-text 'city/area' into coords + names via Nominatim."""
    if not text or not text.strip():
        return None
    params = {"q": text.strip(), "format": "jsonv2", "limit": 1, "addressdetails": 1}
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
            rows = client.get(_nominatim_search_url(), params=params).json()
    except Exception:
        return None
    if not rows:
        return None
    top = rows[0]
    addr = top.get("address") or {}
    city = (
        addr.get("city") or addr.get("town")
        or addr.get("state_district") or addr.get("county")
        or addr.get("municipality") or addr.get("village")
    )
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
        "country_code": (addr.get("country_code") or "").lower(),
        "display_name": top.get("display_name"),
        "matched": top.get("display_name"),
    }


def ip_location(ip: str | None = None) -> dict[str, Any] | None:
    """City-level location from the client IP via ip-api.com (free, no key)."""
    if ip:
        url = f"http://ip-api.com/json/{ip}?fields={IP_FIELDS}"
    else:
        url = f"http://ip-api.com/json?fields={IP_FIELDS}"
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
            data = client.get(url).json()
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("status") != "success":
        return None
    return {
        "lat": float(data.get("lat") or 0),
        "lon": float(data.get("lon") or 0),
        "city": data.get("city"),
        "area": "",
        "state": data.get("regionName"),
        "country": data.get("country"),
        "country_code": (data.get("countryCode") or "").lower(),
    }


def _gps_confidence(accuracy_m: float | None) -> float:
    if accuracy_m is None or accuracy_m <= 0:
        return 0.82
    if accuracy_m <= 50:
        return 0.92
    if accuracy_m <= 200:
        return 0.85
    if accuracy_m <= 1000:
        return 0.70
    if accuracy_m <= 5000:
        return 0.50
    return 0.35


def _default_location() -> dict[str, Any]:
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
        "country": "",
        "country_code": "",
        "accuracy_m": None,
    }


def resolve_location(
    lat: float | None = None,
    lon: float | None = None,
    user_label: str | None = None,
    ip: str | None = None,
    accuracy_m: float | None = None,
) -> dict[str, Any]:
    """Pick the most confident location source and reverse-geocode it.

    Returns a normalized dict with coords, names, source, and confidence.
    ``accuracy_m`` is the browser GPS accuracy (metres) when available — it is
    passed through so the UI can show how precise the fix is. Falls back to the
    configured default city only if everything fails.
    """
    candidates: list[dict[str, Any]] = []

    if user_label and user_label.strip():
        geo = geocode_text(user_label)
        if geo and geo.get("lat") and geo.get("lon"):
            candidates.append(
                {
                    "lat": geo["lat"],
                    "lon": geo["lon"],
                    "source": "user",
                    "confidence": 0.98,
                    "label": user_label.strip(),
                    "names": geo,
                }
            )

    if lat is not None and lon is not None:
        candidates.append(
            {
                "lat": float(lat),
                "lon": float(lon),
                "source": "gps",
                "confidence": _gps_confidence(accuracy_m),
                "label": "browser GPS",
            }
        )

    ip_res = ip_location(ip)
    if ip_res and ip_res.get("lat") and ip_res.get("lon"):
        candidates.append(
            {
                "lat": ip_res["lat"],
                "lon": ip_res["lon"],
                "source": "ip",
                "confidence": 0.45,
                "label": "IP location" + (f" ({ip_res.get('city')})" if ip_res.get("city") else ""),
                "names": ip_res,
            }
        )

    if not candidates:
        return _default_location()

    best = max(candidates, key=lambda c: c["confidence"])
    resolved = reverse_geocode(best["lat"], best["lon"])
    pre = best.get("names") or {}
    city = resolved.get("city") or pre.get("city")
    area = resolved.get("area") or pre.get("area") or ""
    state = resolved.get("state") or pre.get("state") or ""
    country = resolved.get("country") or pre.get("country") or ""
    country_code = (
        resolved.get("country_code") or pre.get("country_code") or ""
    )
    return {
        "lat": best["lat"],
        "lon": best["lon"],
        "source": best["source"],
        "confidence": best["confidence"],
        "label": best["label"],
        "gps_live": best["source"] == "gps",
        "user_override": best["source"] == "user",
        "accuracy_m": float(accuracy_m) if accuracy_m is not None and accuracy_m > 0 else None,
        "city": city,
        "area": area,
        "state": state,
        "country": country,
        "country_code": country_code,
        "display_name": resolved.get("display_name") or pre.get("display_name"),
    }
