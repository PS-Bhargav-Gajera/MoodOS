"""Shared location geometry and the single coordinate contract for all tools.

Every location-aware MCP tool resolves and validates its coordinates through
this module. Geocoding lives here too (`moodos.location` does the provider
calls and delegates the geometry to us) so no tool can grow its own copy.

Contract:
  * `validate_coords` is the ONLY range/swap check, called by every tool.
  * `normalize_places` is the ONLY place-result shape: it guarantees
    name/address/lat/lon/distance_km/source on every row, drops rows with
    missing or impossible coordinates, filters by radius and sorts by distance.
  * `ProviderUnavailable` is raised when a provider is missing or failing.
    Tools never fall back to a stored/canned list.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from moodos.nlu import haversine_km  # re-exported for callers

__all__ = [
    "LocationError",
    "ProviderUnavailable",
    "haversine_km",
    "validate_coords",
    "normalize_places",
    "resolve_tool_coords",
]


class LocationError(ValueError):
    """The request has no usable location, or its coordinates are impossible."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.details}


class ProviderUnavailable(RuntimeError):
    """A required external provider is missing, failing, or rate-limited."""

    def __init__(self, provider: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.provider = provider
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {"error": "provider_unavailable", "provider": self.provider,
                "message": self.message, **self.details}


def _as_float(value: Any) -> float | None:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def validate_coords(lat: Any, lon: Any, *, where: str = "location") -> tuple[float, float]:
    """Range-check a lat/lng pair and reject a swapped pair.

    Raises `LocationError` — never silently repairs or clamps.
    """
    flat, flon = _as_float(lat), _as_float(lon)
    if flat is None or flon is None:
        raise LocationError(
            "invalid_coords",
            f"{where}: latitude and longitude must both be numbers, got "
            f"lat={lat!r} lon={lon!r}.",
            lat=lat, lon=lon,
        )

    lat_ok = -90.0 <= flat <= 90.0
    lon_ok = -180.0 <= flon <= 180.0
    if lat_ok and lon_ok:
        return flat, flon

    # A latitude squeezed out of its range while the longitude still fits one
    # is the classic swap (the caller passed (lon, lat)). Only claim a swap
    # when swapping actually makes both halves valid, otherwise it is simply
    # out of range.
    if (not lat_ok) and (-90.0 <= flon <= 90.0) and (-180.0 <= flat <= 180.0):
        raise LocationError(
            "coords_swapped",
            f"{where}: latitude {flat} is outside [-90, 90] but longitude {flon} "
            f"fits a latitude, so lat/lng appear to be swapped. Send lat in "
            f"[-90, 90] and lng in [-180, 180].",
            lat=flat, lon=flon,
            suggestion={"lat": flon, "lon": flat},
        )

    raise LocationError(
        "coords_out_of_range",
        f"{where}: lat={flat} lon={flon} is out of range "
        f"(lat must be within [-90, 90], lng within [-180, 180]).",
        lat=flat, lon=flon,
    )


def resolve_tool_coords(lat: Any, lon: Any, *, tool: str) -> tuple[float, float]:
    """The one entry point every location tool uses for its coordinates."""
    return validate_coords(lat, lon, where=f"tool {tool}")


def normalize_places(
    items: Iterable[dict[str, Any]] | None,
    lat: float,
    lon: float,
    *,
    radius_km: float | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Shape provider rows into the contract every place tool returns.

    Guarantees on each row: `name`, `address`, `lat`, `lon`, `distance_km`,
    `source`. Rows without usable coordinates are dropped rather than shipped
    with a null position, rows outside `radius_km` are filtered out, and the
    list is sorted nearest-first.
    """
    origin_lat, origin_lon = validate_coords(lat, lon, where="place search origin")
    out: list[dict[str, Any]] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        plat = _as_float(raw.get("lat"))
        plon = _as_float(raw.get("lon"))
        if plat is None or plon is None:
            continue  # never return a result with missing coordinates
        try:
            validate_coords(plat, plon, where="place result")
        except LocationError:
            continue

        name = str(raw.get("name") or raw.get("title") or "").strip()
        if not name:
            continue

        distance = _as_float(raw.get("distance_km"))
        if distance is None:
            distance = haversine_km(origin_lat, origin_lon, plat, plon)
        distance = round(max(distance, 0.0), 3)
        if radius_km is not None and distance > float(radius_km):
            continue

        address = raw.get("address")
        out.append({
            **raw,
            "name": name,
            "title": str(raw.get("title") or name),
            "address": str(address).strip() if address else "",
            "lat": plat,
            "lon": plon,
            "distance_km": distance,
            "source": str(raw.get("source") or "unknown"),
        })

    out.sort(key=lambda p: p["distance_km"])
    if limit is not None:
        out = out[: max(1, int(limit))]
    return out
