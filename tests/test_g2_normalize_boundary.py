"""G2: normalize_places is the boundary every place tool's results pass through.

Two live-plan bugs live here:
  * the "Nearby Restaurants" panel showed only a pin (no distance) for
    Overpass-sourced rows, because nothing ever set `distance_label`;
  * canteen rows such as "Law Canteen(F2)" reached the panel from results
    cached before G1 - a cache hit returns early and never re-filters, so the
    filter has to run again at the boundary.

Plus one panel defect: the same venue could appear twice (two OSM rows, same
name within 100 m), which normalize_places never deduped.
"""

from moodos.geo import normalize_places

AHMEDABAD = (23.03, 72.58)


def _row(name, lat, lon, **kw):
    return {"name": name, "lat": lat, "lon": lon, "source": "overpass", **kw}


def test_normalize_places_sets_distance_label():
    rows = normalize_places([_row("Chai Point", 23.034, 72.58)], *AHMEDABAD, radius_km=5)
    label = rows[0].get("distance_label")
    assert label, "normalize_places must guarantee distance_label"
    assert label.endswith(" km")
    assert label[0].isdigit()


def test_normalize_places_keeps_a_provider_supplied_distance_label():
    rows = normalize_places(
        [_row("Cafe A", 23.031, 72.58, distance_label="400 m from you")],
        *AHMEDABAD,
        radius_km=5,
    )
    assert rows[0]["distance_label"] == "400 m from you"


def test_normalize_places_drops_institutional_canteens():
    rows = normalize_places(
        [
            _row("Law Canteen(F2)", 23.031, 72.581),
            _row("Pharma Canteen(F1)", 23.032, 72.582),
            _row("Staff Cafeteria", 23.033, 72.583),
            _row("Saganwala Restaurant", 23.034, 72.584),
            _row("Chai Point", 23.035, 72.585),
        ],
        *AHMEDABAD,
        radius_km=5,
    )
    assert [r["name"] for r in rows] == ["Saganwala Restaurant", "Chai Point"]


def test_normalize_places_dedupes_same_venue_within_100m():
    rows = normalize_places(
        [
            _row("Saganwala Restaurant", 23.0340, 72.5800),
            _row("Saganwala Restaurant", 23.0345, 72.5800),  # ~55 m apart
            _row("Chai Point", 23.0340, 72.5810),
        ],
        *AHMEDABAD,
        radius_km=5,
    )
    assert [r["name"] for r in rows] == ["Saganwala Restaurant", "Chai Point"]
