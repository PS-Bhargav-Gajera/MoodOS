"""Live smoke: two far-apart cities + GPS vs typed input, through the MCP tools.

Run manually (NOT part of pytest — it hits real providers on purpose):
    python scripts/smoke_location_live.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moodos.geo import LocationError, ProviderUnavailable, haversine_km  # noqa: E402
from moodos.location import geocode_text, resolve_location  # noqa: E402
from moodos.mcp_server import mcp  # noqa: E402

AHMEDABAD = (23.0225, 72.5714)
MUMBAI = (19.0760, 72.8777)
DELHI = (28.6139, 77.2090)


def _line(label: str, value: object) -> None:
    print(f"  {label:<28} {value}")


def main() -> int:
    print("=== 1. geocode two far-apart typed cities (real Nominatim) ===")
    for city in ("Mumbai", "Delhi"):
        g = geocode_text(city)
        assert g, f"geocode failed for {city}"
        _line(city, f"{g['lat']}, {g['lon']}  |  {g.get('display_name')}")
    _line("distance Mumbai<->Delhi",
          f"{haversine_km(*MUMBAI, *DELHI):.1f} km")

    print("\n=== 2. resolve_location priority ===")
    r = resolve_location(*AHMEDABAD, "Mumbai", None, accuracy_m=12)
    _line("typed Mumbai + GPS Ahd", f"{r['source']} {r['lat']}, {r['lon']} ({r['city']})")
    assert r["source"] == "user" and (r["lat"], r["lon"]) != AHMEDABAD

    r = resolve_location(*AHMEDABAD, None, None)
    _line("GPS only", f"{r['source']} {r['lat']}, {r['lon']} ({r['city']})")
    assert r["source"] == "gps" and (r["lat"], r["lon"]) == AHMEDABAD

    try:
        resolve_location(None, None, "zzzz nowhere", None)
        _line("ungeocodable typed", "NO ERROR (bug)")
        return 1
    except LocationError as exc:
        _line("ungeocodable typed", f"{exc.code}: {exc.message[:60]}...")

    try:
        resolve_location(100.0, 20.0, None, None)
        _line("swapped coords", "NO ERROR (bug)")
        return 1
    except LocationError as exc:
        _line("swapped coords", f"{exc.code}")

    print("\n=== 3. find_nearby_places: results change + stay in radius ===")
    for name, (la, lo) in (("Mumbai", MUMBAI), ("Delhi", DELHI)):
        try:
            rows = mcp.call("find_nearby_places", lat=la, lon=lo, q="cafe", radius_m=4000)
        except ProviderUnavailable as exc:
            _line(name, f"provider unavailable: {exc.message[:60]}")
            continue
        if not rows:
            _line(name, "0 rows (Overpass breaker open or empty area)")
            continue
        worst = max(r["distance_km"] for r in rows)
        _line(name, f"{len(rows)} cafes, nearest={rows[0]['name']} "
                    f"@{rows[0]['distance_km']}km, farthest={worst}km")
        assert worst <= 4.0, f"{name}: row outside radius {worst}"
        for r in rows:
            for field in ("name", "address", "lat", "lon", "distance_km", "source"):
                assert field in r, f"{name}: row missing {field}"

    print("\n=== 4. get_weather (Open-Meteo) ===")
    for name, (la, lo) in (("Mumbai", MUMBAI), ("Delhi", DELHI)):
        try:
            w = mcp.call("get_weather", lat=la, lon=lo)
            _line(name, f"{w.get('temperature_c')}C  {w.get('condition')}  "
                        f"({w.get('source')})")
        except ProviderUnavailable as exc:
            _line(name, f"provider unavailable: {exc.message[:60]}")

    print("\n=== 5. search_restaurants: same shape contract ===")
    try:
        rows = mcp.call("search_restaurants", lat=MUMBAI[0], lon=MUMBAI[1], limit=5)
        _line("Mumbai restaurants", f"{len(rows)} rows")
        for r in rows[:3]:
            _line("  " + r["name"][:24],
                  f"{r['distance_km']}km  addr={r.get('address')!r}  src={r['source']}")
    except ProviderUnavailable as exc:
        _line("Mumbai restaurants", f"provider unavailable: {exc.message[:60]}")

    print("\nALL LIVE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
