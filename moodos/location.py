"""Location Resolver: fuse browser GPS, user-entered location, and IP location
into one best-guess "where am I" with a confidence score, then reverse-geocode
it to a readable city/area/state label.

Priority (fixed order — not a confidence race):
  1. Typed place in the CURRENT request -> geocoded by a real provider
  2. GPS coordinates sent with the request
  3. IP location (device/network derived, city level)
  4. Saved profile location (.env DEFAULT_*) -> always announced to the user
  5. Nothing usable -> LocationError("location_required"); never a silent city
"""

from __future__ import annotations

import os

import httpx
from typing import Any

from moodos.config import settings
from moodos.geo import LocationError, validate_coords
from moodos.providers import HEADERS, TIMEOUT, reverse_geocode




def _nominatim_search_url() -> str:
    return f"{settings.nominatim_url.rstrip('/')}/search"


def geocode_text(text: str) -> dict[str, Any] | None:
    """Forward-geocode a free-text 'city/area' into coords + names via Nominatim.

    Asks for several hits so an ambiguous name ("Springfield") can hand the
    caller the full resolved addresses to confirm, instead of silently picking
    the first one. Ambiguity is flagged when the candidates disagree on
    state or country.
    """
    if not text or not text.strip():
        return None
    params = {"q": text.strip(), "format": "jsonv2", "limit": 5, "addressdetails": 1}
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
            rows = client.get(_nominatim_search_url(), params=params).json()
    except Exception:
        return None
    if not isinstance(rows, list) or not rows:
        return None

    candidates: list[dict[str, Any]] = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        addr = row.get("address") or {}
        try:
            clat, clon = validate_coords(row.get("lat"), row.get("lon"),
                                         where=f'geocode "{text}"')
        except LocationError:
            continue
        candidates.append({
            "lat": clat,
            "lon": clon,
            "display_name": row.get("display_name"),
            "city": (addr.get("city") or addr.get("town") or addr.get("village")
                     or addr.get("county")),
            "state": addr.get("state"),
            "country": addr.get("country"),
            "country_code": (addr.get("country_code") or "").lower(),
        })
    if not candidates:
        return None

    # A bare place name that resolves into more than one state/country is the
    # ambiguous case ("Springfield"). A full address already disambiguates, so
    # it is left alone rather than nagging the user with a confirmation.
    distinct = {(c.get("country_code"), c.get("state")) for c in candidates}
    ambiguous = (
        len(candidates) > 1
        and len(distinct) > 1
        and "," not in text
    )

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
        "lat": candidates[0]["lat"],
        "lon": candidates[0]["lon"],
        "city": city,
        "area": area,
        "state": addr.get("state"),
        "country": addr.get("country"),
        "country_code": candidates[0]["country_code"],
        "display_name": top.get("display_name"),
        "matched": top.get("display_name"),
        "candidates": candidates,
        "ambiguous": ambiguous,
    }



def ip_location(ip: str | None = None) -> dict[str, Any] | None:
    """City-level location from the client IP via ipwho.is (free, HTTPS, no key).

    ip-api.com was the previous source but its free tier has no HTTPS at all
    ("SSL is not available for this free API" per their docs), so the client IP
    was sent in cleartext. ipwho.is serves the same city-level data over HTTPS.
    """
    url = f"https://ipwho.is/{ip}" if ip else "https://ipwho.is/"
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
            data = client.get(url).json()
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("success"):
        return None
    return {
        "lat": float(data.get("latitude") or 0),
        "lon": float(data.get("longitude") or 0),
        "city": data.get("city"),
        "area": "",
        "state": data.get("region"),
        "country": data.get("country"),
        "country_code": (data.get("country_code") or "").lower(),
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


def _profile_location() -> dict[str, Any] | None:
    """The saved profile location, but only when it was actually configured.

    The raw environment (not `settings`, which always has compiled-in
    fallbacks) decides this: a project that never set DEFAULT_LAT/LON/CITY has
    no saved location and must ask the user instead of inventing a city.
    """
    has_lat = bool(os.environ.get("DEFAULT_LAT", "").strip())
    has_lon = bool(os.environ.get("DEFAULT_LON", "").strip())
    if not (has_lat and has_lon):
        # Absent, or half-configured (city but no coords, or vice versa) is
        # not a usable saved fix — ask the user instead of mixing a typed city
        # with compiled-in code defaults.
        return None
    try:
        plat, plon = validate_coords(settings.default_lat, settings.default_lon,
                                     where="saved profile location")
    except LocationError:
        return None
    return {
        "lat": plat,
        "lon": plon,
        "source": "profile",
        "confidence": 0.10,
        "label": f"saved profile location ({settings.default_city})",
        "notice": (
            f"No live location for this request — using your saved profile "
            f"location: {settings.default_city}."
        ),
    }


def resolve_location(
    lat: float | None = None,
    lon: float | None = None,
    user_label: str | None = None,
    ip: str | None = None,
    accuracy_m: float | None = None,
) -> dict[str, Any]:
    """Resolve the request's location under the fixed priority order.

    Typed place > GPS > IP > saved profile > `LocationError("location_required")`.
    Coordinates are validated (range + swap) before they are trusted, an
    ambiguous typed name comes back flagged with its candidate addresses, and
    a profile fallback always carries a `notice` so it is never silent.
    """
    candidates: list[dict[str, Any]] = []

    typed = (user_label or "").strip()
    if typed:
        geo = geocode_text(typed)
        if not geo or geo.get("lat") is None or geo.get("lon") is None:
            raise LocationError(
                "geocode_failed",
                f'Could not geocode "{typed}" to a real place. Type a city or '
                f'address, or allow GPS.',
                query=typed,
            )
        tlat, tlon = validate_coords(geo["lat"], geo["lon"],
                                     where=f'typed location "{typed}"')
        cand = {
            "lat": tlat,
            "lon": tlon,
            "source": "user",
            "confidence": 0.98,
            "label": typed,
            "names": geo,
        }
        if geo.get("ambiguous"):
            # Ambiguous name: return the full resolved addresses so the caller
            # can make the user confirm instead of silently picking one.
            cand["needs_confirmation"] = True
            cand["candidates"] = geo.get("candidates") or []
            cand["display_name"] = geo.get("display_name")
            cand["notice"] = (
                f'"{typed}" matches more than one place. Confirm which one you '
                f"mean: " + "; ".join(
                    str(c.get("display_name") or "")
                    for c in cand["candidates"][:5] if c.get("display_name")
                )
            )
        candidates.append(cand)

    if lat is not None or lon is not None:
        if lat is None or lon is None:
            raise LocationError(
                "invalid_coords",
                "A GPS fix must include both latitude and longitude, "
                f"got lat={lat!r} lon={lon!r}.",
                lat=lat, lon=lon,
            )
        glat, glon = validate_coords(lat, lon, where="browser GPS")
        candidates.append(
            {
                "lat": glat,
                "lon": glon,
                "source": "gps",
                "confidence": _gps_confidence(accuracy_m),
                "label": "browser GPS",
            }
        )

    # Lower-priority sources are only consulted when nothing better already
    # resolved — an IP lookup is a wasted network round-trip otherwise.
    if not candidates:
        ip_res = ip_location(ip)
        if ip_res and ip_res.get("lat") is not None and ip_res.get("lon") is not None:
            try:
                ilat, ilon = validate_coords(ip_res["lat"], ip_res["lon"],
                                             where="IP location")
            except LocationError:
                ilat = ilon = None
            if ilat is not None:
                candidates.append(
                    {
                        "lat": ilat,
                        "lon": ilon,
                        "source": "ip",
                        "confidence": 0.45,
                        "label": "IP location" + (f" ({ip_res.get('city')})" if ip_res.get("city") else ""),
                        "names": ip_res,
                    }
                )

    if not candidates:
        profile = _profile_location()
        if profile:
            candidates.append(profile)

    if not candidates:
        raise LocationError(
            "location_required",
            "Location required: no GPS coordinates, no typed place, no IP "
            "location and no saved profile location for this request. Send "
            "lat/lng or type a place name.",
        )

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
        "needs_confirmation": bool(best.get("needs_confirmation")),
        "candidates": best.get("candidates") or [],
        "notice": best.get("notice"),
    }
