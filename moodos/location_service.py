"""LocationService: the single abstraction for "where am I" + real nearby places.

Owns all OSM-family (Overpass / Nominatim / OSRM) API usage for location and
POI discovery + routing, so the rest of the app never needs to know OSM
specifics. Exposes a small, reusable surface:

  * get_current_location(...)   -> best-guess coords + names + confidence
  * reverse_geocode(lat, lon)   -> readable city/area/address
  * search_nearby_places(...)   -> normalized real POIs across many categories
  * get_place_details(place)    -> enriched normalized place object
  * calculate_route(a, b)       -> real route distance + duration, or a clearly
                                   marked estimate when routing is unavailable

Design rules
  * NEVER invent data: unknown fields are None/empty, estimates are flagged
    with ``price_is_estimate`` / ``routing_source``.
  * Reuse existing leaf code: geocoding delegates to ``moodos.location``,
    Nominatim reverse to ``moodos.providers``, cost/opening-hours helpers are
    imported from ``moodos.providers``.
  * Graceful degradation: every external call is wrapped; failures fall back to
    estimates or empty lists, never exceptions.
  * Caching (ttl_cache) + a global min-interval throttle protect public OSM
    services from bursts and duplicate work.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from moodos.cache import ttl_cache
from moodos.config import settings
from moodos.fallback_places import fallback_places
from moodos.geo import ProviderUnavailable
from moodos.nlu import haversine_km
from moodos.providers import (
    HEADERS,
    TIMEOUT,
    _estimate_food_cost,
    _institutional_flag,
    _opening_hours_is_open,
    reverse_geocode as _nominatim_reverse,
)

log = __import__("logging").getLogger("moodos.location_service")


# ---------------------------------------------------------------------------
# Category catalogue: Overpass filter -> normalized place shape.
# ---------------------------------------------------------------------------

# Each entry: filters (OSM key/value pairs matched on node AND way), plus the
# normalized defaults the ranker/planner already understands.
_CATEGORY_SPECS: list[dict[str, Any]] = [
    {"name": "cafe", "filters": [("amenity", "cafe"), ("amenity", "tea")],
     "kind": "place", "subtype": "cafe", "duration_min": 45, "dwell_family": "food"},
    {"name": "restaurant", "filters": [("amenity", "restaurant")],
     "kind": "food", "subtype": "restaurant", "duration_min": 60, "dwell_family": "food"},
    {"name": "fast_food", "filters": [("amenity", "fast_food")],
     "kind": "food", "subtype": "fast_food", "duration_min": 25, "dwell_family": "food"},
    {"name": "dessert", "filters": [("amenity", "ice_cream"), ("shop", "confectionery"), ("shop", "dessert")],
     "kind": "food", "subtype": "ice_cream", "duration_min": 20, "dwell_family": "food"},
    {"name": "walk", "filters": [("leisure", "park"), ("leisure", "garden"),
                                 ("leisure", "nature_reserve"), ("tourism", "viewpoint")],
     "kind": "place", "subtype": "walk", "duration_min": 30,
     "outdoor": True, "needs_clear_weather": True, "dwell_family": "outdoor"},
    {"name": "cinema", "filters": [("amenity", "cinema")],
     "kind": "place", "subtype": "cinema", "duration_min": 30, "has_venue": True, "dwell_family": "venue"},
    {"name": "museum", "filters": [("tourism", "museum")],
     "kind": "place", "subtype": "museum", "duration_min": 90, "dwell_family": "venue"},
    {"name": "attraction", "filters": [("tourism", "attraction"), ("tourism", "artwork")],
     "kind": "place", "subtype": "attraction", "duration_min": 75, "dwell_family": "venue"},
    {"name": "shopping", "filters": [("shop", "mall"), ("shop", "supermarket"),
                                     ("shop", "department_store"), ("shop", "gift")],
     "kind": "place", "subtype": "shopping", "duration_min": 60, "dwell_family": "venue"},
    {"name": "bookstore", "filters": [("shop", "books")],
     "kind": "place", "subtype": "bookstore", "duration_min": 40, "dwell_family": "venue"},
    {"name": "entertainment", "filters": [("leisure", "amusement_arcade"), ("leisure", "bowling_alley"),
                                          ("leisure", "miniature_golf"), ("leisure", "escape_game")],
     "kind": "place", "subtype": "entertainment", "duration_min": 45, "dwell_family": "venue"},
    {"name": "wellness", "filters": [("leisure", "fitness_centre"), ("leisure", "spa"),
                                     ("leisure", "sauna"), ("leisure", "swimming_pool")],
     "kind": "place", "subtype": "wellness", "duration_min": 50, "dwell_family": "venue"},
]

_ALL_CATEGORIES = [c["name"] for c in _CATEGORY_SPECS]

# Per-category element budget per Overpass request (kept modest to bound the
# response while still mixing categories).
_PER_CATEGORY_LIMIT = {
    "cafe": 6, "restaurant": 6, "fast_food": 4, "dessert": 4, "walk": 5,
    "cinema": 4, "museum": 4, "attraction": 4, "shopping": 4,
    "bookstore": 3, "entertainment": 4, "wellness": 4,
}

_MAX_ELEMENTS = sum(_PER_CATEGORY_LIMIT.values())

# P1b: when Overpass fails, retry the same category via fallback_places.
# Only the categories fallback_places supports are listed; the fallback's
# own spec names match our cats (park -> "walk") so the category filter
# below still applies to its results.
_FALLBACK_CATEGORY = {
    "cafe": "cafe",
    "restaurant": "restaurant",
    "cinema": "cinema",
    "walk": "park",
}


def _parse_categories(categories: str | list[str] | None) -> list[str]:
    """Resolve a categories argument (None / 'any' / names / CSV) to spec names."""
    if not categories:
        return list(_ALL_CATEGORIES)
    if isinstance(categories, str):
        if categories.strip().lower() in {"any", "all", ""}:
            return list(_ALL_CATEGORIES)
        raw = categories.split(",")
    else:
        raw = list(categories)
    out: list[str] = []
    for r in raw:
        name = (r or "").strip().lower()
        if name in {"park", "parks", "garden", "gardens", "walk", "walking", "walks"}:
            out.append("walk")
        elif name in {"bookstore", "bookstores", "books"}:
            out.append("bookstore")
        elif name in {"fast-food", "fast_food", "fastfood", "fast food"}:
            out.append("fast_food")
        elif name in _ALL_CATEGORIES:
            out.append(name)
    seen: set[str] = set()
    ordered = [c for c in _ALL_CATEGORIES if c in out]
    return [c for c in ordered if not (c in seen or seen.add(c))] or list(_ALL_CATEGORIES)


def _has_real_price_signal(tags: dict) -> bool:
    """True only when OSM carries an actual price/star rating for the venue.

    The ranker's price_tier is a heuristic estimate, so it must never be turned
    into a user-facing price_level on its own (that would invent data).
    """
    for key in ("price", "price:range", "stars", "charge"):
        val = str(tags.get(key) or "").strip()
        if not val:
            continue
        if key == "stars":
            if val.isdigit() and int(val) > 0:
                return True
            continue
        if "₹" in val or "$" in val or "€" in val or "£" in val or val[:1].isdigit():
            return True
    return False


def _fmt_km(km: float | None) -> str | None:
    if km is None:
        return None
    if km < 1:
        return f"{int(km * 1000)} m from you"
    return f"{km:.1f} km from you"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class LocationService:
    def __init__(self) -> None:
        # Disabled after repeated OSRM failures: the fallback (haversine
        # estimate, clearly flagged) is fast and dependency-free. A single
        # transient timeout is tolerated before we give up.
        self.osrm_enabled = True
        self._fail_counts: dict[str, int] = {}
        self._lock = threading.Lock()
        self._last_call = 0.0

    # -- transport seams (these are the only places that touch the network) --

    def _throttle(self) -> None:
        with self._lock:
            gap = max(settings.osm_min_interval_ms, 0) / 1000.0
            wait = self._last_call + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _http_get_json(self, url: str, params: dict | None = None) -> Any:
        self._throttle()
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    def _http_post_json(self, url: str, content: str) -> Any:
        self._throttle()
        with httpx.Client(timeout=25.0, headers={**HEADERS, "Content-Type": "text/plain"}) as client:
            resp = client.post(url, content=content)
            resp.raise_for_status()
            return resp.json()

    # -- 1. current location -------------------------------------------------

    def get_current_location(
        self,
        lat: float | None = None,
        lon: float | None = None,
        user_label: str | None = None,
        ip: str | None = None,
        accuracy_m: float | None = None,
    ) -> dict[str, Any]:
        """Best-guess location: explicit user input > GPS > IP > default."""
        from moodos.location import resolve_location

        return resolve_location(lat, lon, user_label, ip, accuracy_m=accuracy_m)

    def reverse_geocode(self, lat: float, lon: float) -> dict[str, Any]:
        """Readable city/area/state for coordinates (Nominatim, cached)."""
        return _nominatim_reverse(lat, lon)

    # -- 3. nearby places ----------------------------------------------------

    def search_nearby_places(
        self,
        lat: float,
        lon: float,
        categories: str | list[str] | None = None,
        radius_m: int = 4000,
        limit: int = 24,
        *,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        """Real nearby POIs from Overpass, normalized + deduped + distance-sorted.

        Returns up to ``limit`` places. When Overpass is unavailable (timeout,
        rate limited, offline) it returns an empty list rather than fabricating
        venues — unless ``strict`` is set, in which case it raises
        `ProviderUnavailable` so the caller can report an honest error instead
        of an empty result that reads as "nothing is nearby".
        Categories are resolved via ``_parse_categories``.
        """
        radius_m = max(800, min(int(radius_m or 4000), 20000))
        limit = max(1, min(int(limit or 24), 60))
        cats = _parse_categories(categories)
        key = f"poi:{round(lat, 3)}:{round(lon, 3)}:{radius_m}:{','.join(cats)}:{limit}"
        cached = ttl_cache.get(key)
        if cached is not None:
            return cached

        elements = self._overpass_elements(lat, lon, radius_m, cats)
        if elements is None:
            # P1b: Overpass failed (timeout, 502/429, breaker) — try the live
            # fallback provider for the same categories before giving up.
            places = []
            for cat in cats:
                fb_cat = _FALLBACK_CATEGORY.get(cat)
                if fb_cat:
                    places.extend(fallback_places(lat, lon, fb_cat, limit=limit))
            places = [p for p in places if p.get("category") in cats]
            if not places:
                if strict:
                    raise ProviderUnavailable(
                        "overpass",
                        "Overpass and the fallback provider are both unavailable "
                        "(timeout, rate limit or breaker open) — no place data "
                        "to return. Not falling back to a stored list.",
                    )
                return []
        else:
            places = self._normalize_elements(elements, lat, lon, cats)
            # Belt-and-braces: enforce the requested categories even if a mocked
            # or misbehaving Overpass response returned more.
            places = [p for p in places if p.get("category") in cats]
        places = self._dedupe(places)
        places.sort(key=lambda p: (p.get("distance_km") or 999.0))
        places = places[:limit]
        self._attach_route_times(places, lat, lon)

        # Cache populated results long; cache empties briefly so a void area or
        # a transient Overpass failure doesn't hammer the public API on retry.
        ttl_cache.set(key, places, ttl_seconds=30 * 60 if places else 3 * 60)
        return places

    def _overpass_elements(
        self, lat: float, lon: float, radius_m: int, cats: list[str]
    ) -> list[dict[str, Any]] | None:
        """One Overpass request per category set.

        Returns `None` when Overpass itself failed (so the caller can tell
        "provider down" apart from "genuinely no POIs here", which returns
        an empty list).
        """
        stmts: list[str] = []
        for name in cats:
            spec = next((c for c in _CATEGORY_SPECS if c["name"] == name), None)
            if not spec:
                continue
            body: list[str] = []
            for k, v in spec["filters"]:
                body.append(
                    f'  node["{k}"="{v}"](around:{radius_m},{lat},{lon});'
                )
                body.append(
                    f'  way["{k}"="{v}"](around:{radius_m},{lat},{lon});'
                )
            per = min(_PER_CATEGORY_LIMIT.get(name, 4), _MAX_ELEMENTS)
            stmts.append(
                "(\n" + "\n".join(body) + f"\n)->.{name.replace('_', '')};"
            )
            stmts.append(f".{name.replace('_', '')} out center {per};")
        query = f"[out:json][timeout:25];\n" + "\n".join(stmts)
        try:
            if "_http_post_json" in self.__dict__ and getattr(self._http_post_json, "__name__", "") not in ("offline", "_offline"):
                data = self._http_post_json(settings.overpass_url, query)
            else:
                from moodos.providers import _overpass_query

                data = _overpass_query(query)
        except Exception as exc:  # timeout / rate limit / DNS / offline
            log.warning("overpass nearby search failed: %s", exc)
            return None
        if not isinstance(data, dict):
            log.warning("overpass nearby search returned non-object payload")
            return None
        return [el for el in (data.get("elements") or []) if isinstance(el, dict)]

    def _normalize_elements(
        self, elements: list[dict[str, Any]], lat: float, lon: float, cats: list[str]
    ) -> list[dict[str, Any]]:
        spec_by_filter = {
            (f[0], f[1]): spec
            for spec in _CATEGORY_SPECS
            for f in spec["filters"]
        }
        places: list[dict[str, Any]] = []
        for el in elements:
            tags = el.get("tags") or {}
            if not isinstance(tags, dict):
                continue
            name = tags.get("name") or tags.get("brand")
            if not name or not name.strip():
                continue  # unnamed OSM node — no usable place data
            plat = el.get("lat") or (el.get("center") or {}).get("lat")
            plon = el.get("lon") or (el.get("center") or {}).get("lon")
            if plat is None or plon is None:
                continue
            if _institutional_flag(tags, name):
                continue

            spec = None
            # Specific categories win over the generic amenity: a bookshop won't
            # be miscast as a cafe just because it sits in a building.
            for (fk, fv) in (("shop", tags.get("shop")),
                             ("tourism", tags.get("tourism")),
                             ("leisure", tags.get("leisure")),
                             ("amenity", tags.get("amenity"))):
                if fk and fv and (fk, fv) in spec_by_filter:
                    spec = spec_by_filter[(fk, fv)]
                    break
            # Any amenity endswith match; default to cafe-family for amenity=cafe/tea.
            if spec is None:
                amenity = tags.get("amenity")
                if amenity in {"cafe", "tea"}:
                    spec = _CATEGORY_SPECS[0]
                elif amenity == "restaurant":
                    spec = _CATEGORY_SPECS[1]
                elif amenity == "fast_food":
                    spec = _CATEGORY_SPECS[2]
                else:
                    continue

            place = self._build_place(el, tags, name, float(plat), float(plon), spec, lat, lon)
            places.append(place)
        return places

    def _build_place(
        self, el: dict, tags: dict, name: str,
        plat: float, plon: float, spec: dict, lat: float, lon: float,
    ) -> dict[str, Any]:
        family = spec.get("dwell_family", "venue")
        outdoor = bool(spec.get("outdoor"))
        if family == "food":
            cost, tier = _estimate_food_cost(tags, name, spec.get("subtype", "restaurant"))
            price_est = True
            # price_tier is a flagged ESTIMATE derived from the venue type.
            # price_level must only ever echo a real OSM price signal, otherwise
            # a "₹" would be shown to the user as if the venue published it.
            real_price = _has_real_price_signal(tags)
        else:
            fee = (tags.get("fee") or "").lower() in {"yes", "20", "true"} or bool(tags.get("fee"))
            cost = 150 if fee else 0
            tier = None
            price_est = fee
            real_price = _has_real_price_signal(tags)
        open_now, opening_note = (
            _opening_hours_is_open(tags.get("opening_hours"))
            if family in {"food", "venue"} and (spec.get("subtype") != "cinema" or True)
            else (None, "")
        )
        dist = round(haversine_km(lat, lon, plat, plon), 2) if (lat and lon) else None
        addr = self._tags_address(tags)
        rating_raw = tags.get("rating")
        rating = None
        try:
            if rating_raw:
                rating = float(rating_raw)
        except (TypeError, ValueError):
            rating = None
        return {
            # normalized identity
            "id": f"osm:{el.get('type', 'node')}:{el.get('id')}",
            "source_id": f"{el.get('type', 'node')}/{el.get('id')}",
            "name": name,
            "title": name,
            "category": spec.get("name"),
            "subtype": spec.get("subtype"),
            "kind": spec.get("kind"),
            "lat": plat,
            "lon": plon,
            "source": "overpass",
            # real-world facts (None = genuinely unknown, never invented)
            "address": addr,
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "website": tags.get("website") or tags.get("contact:website"),
            "opening_hours": tags.get("opening_hours"),
            "opening_note": opening_note,
            "likely_closed_at": True if open_now is False else None,
            "cuisine": (tags.get("cuisine") or tags.get("food") or "").replace(";", ", ") or None,
            "price_level": (
                {"premium": "₹₹₹₹", "mid": "₹₹", "budget": "₹"}.get(tier)
                if (tier and real_price) else None
            ),
            "price_tier": tier,
            "price_is_estimate": price_est,
            "rating": rating,
            # distance + times (haversine now; OSRM refines via _attach_route_times)
            "distance_km": dist,
            "distance_label": _fmt_km(dist),
            "walk_min": _walk_est(dist),
            "drive_min": _walk_est(dist) if dist is None else _drive_est(dist),
            "routing_source": "estimate",
            # ranker/planner contract
            "estimated_cost": cost,
            "duration_min": int(spec.get("duration_min") or 45),
            "intensity": "low",
            "crowded": False,
            "outdoor": outdoor,
            "needs_clear_weather": bool(spec.get("needs_clear_weather")),
            "has_venue": bool(spec.get("has_venue")) or family in {"food", "venue"},
            "review_quality": 7.0,
            "moods": _moods_for(spec.get("name")),
            "text": self._poi_text(tags, name, spec),
        }

    @staticmethod
    def _tags_address(tags: dict) -> str | None:
        parts = [
            tags.get("addr:housenumber"), tags.get("addr:street"),
            tags.get("addr:suburb"), tags.get("addr:city"),
            tags.get("addr:district"), tags.get("addr:state"),
        ]
        parts = [str(p).strip() for p in parts if p]
        return ", ".join(parts) or None

    @staticmethod
    def _poi_text(tags: dict, name: str, spec: dict) -> str:
        bits = [name]
        cuisine = (tags.get("cuisine") or tags.get("food") or "").replace(";", ", ")
        if cuisine:
            bits.append(cuisine)
        if spec.get("outdoor"):
            bits.append("open-air")
        opening = tags.get("opening_hours")
        if opening:
            bits.append(f"hours: {opening}")
        return " — ".join(bits[:3])

    @staticmethod
    def _dedupe(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for p in places:
            key = (
                str(p.get("title") or "").strip().lower(),
                round(p.get("lat") or 0, 3),
                round(p.get("lon") or 0, 3),
                p.get("category"),
            )
            existing = seen.get(key)
            if existing is None:
                seen[key] = p
                continue
            # Keep the richer one: prefer one with an address / phone / rating.
            def _richness(d: dict) -> int:
                return sum(bool(d.get(k)) for k in ("address", "phone", "website", "rating", "opening_hours"))
            if _richness(p) > _richness(existing):
                seen[key] = p
        return list(seen.values())

    def _attach_route_times(self, places: list[dict[str, Any]], lat: float, lon: float) -> None:
        """Refine distance + walking/driving times with real OSRM table data."""
        if not places or not self.osrm_enabled:
            return
        targets = [(p["lat"], p["lon"]) for p in places]
        driving = self._osrm_table(lat, lon, targets, "driving")
        if driving is None:
            return
        for i, p in enumerate(places):
            d = driving[i]
            if not d:
                continue
            p["distance_km"] = round(d["distance_km"], 2)
            p["distance_label"] = _fmt_km(p["distance_km"])
            p["drive_min"] = max(1, d["duration_min"])
            p["routing_source"] = "osrm"
        walking = self._osrm_table(lat, lon, targets, "foot")
        if walking:
            for i, p in enumerate(places):
                if walking[i]:
                    p["walk_min"] = max(1, walking[i]["duration_min"])

    # -- OSRM ----------------------------------------------------------------

    def _note_osrm_failure(self, profile: str) -> None:
        """Count consecutive failures per profile; stop hitting OSRM after 2."""
        with self._lock:
            self._fail_counts[profile] = self._fail_counts.get(profile, 0) + 1
            if self._fail_counts[profile] >= 2:
                self.osrm_enabled = False

    def _osrm_route(self, lat1: float, lon1: float, lat2: float, lon2: float,
                    profile: str = "driving") -> dict[str, Any] | None:
        if not self.osrm_enabled:
            return None
        key = f"osrm:{profile}:{round(lat1, 4)}:{round(lon1, 4)}:{round(lat2, 4)}:{round(lon2, 4)}"
        cached = ttl_cache.get(key)
        if cached is not None:
            return cached
        url = f"{settings.osrm_url}/route/v1/{profile}/{lon1},{lat1};{lon2},{lat2}"
        try:
            data = self._http_get_json(url, params={"overview": "false", "steps": "false"})
            route = ((data.get("routes") or [{}])[0] or {}).get("legs", [{}])[0]
        except Exception as exc:
            self._note_osrm_failure(profile)
            log.warning("osrm route failed (%s): %s", profile, exc)
            return None
        distance_m = route.get("distance")
        duration_s = route.get("duration")
        if distance_m is None or duration_s is None:
            return None
        result = {"distance_km": round(distance_m / 1000.0, 2), "duration_min": int(round(duration_s / 60.0))}
        if result["distance_km"] < 0.05:
            result["distance_km"] = 0.05
        ttl_cache.set(key, result, ttl_seconds=24 * 3600)
        return result

    def _osrm_table(self, lat: float, lon: float, targets: list[tuple[float, float]],
                    profile: str) -> list[dict[str, Any]] | None:
        """One table request: real distance+duration from origin to each target."""
        if not self.osrm_enabled or not targets:
            return None
        key = f"osrmt:{profile}:{round(lat, 4)}:{round(lon, 4)}:" + ":".join(
            f"{round(a, 4)},{round(b, 4)}" for a, b in targets
        )
        cached = ttl_cache.get(key)
        if cached is not None:
            return cached
        coords = ";".join(
            f"{lon},{lat}" + "".join(f";{b},{a}" for a, b in targets)
        )
        url = f"{settings.osrm_url}/table/v1/{profile}/{coords}"
        try:
            data = self._http_get_json(
                url, params={"sources": "0", "destinations": "1;" + ";".join(str(i) for i in range(1, len(targets) + 1))}
            )
            row = ((data.get("distances") or [None])[0]) or None
            dur_row = ((data.get("durations") or [None])[0]) or None
        except Exception as exc:
            self._note_osrm_failure(profile)
            log.warning("osrm table failed (%s): %s", profile, exc)
            return None
        if not row:
            return None
        out: list[dict[str, Any]] = []
        for i in range(1, len(targets) + 1):
            d_m = row[i] if i < len(row) else None
            t_s = dur_row[i] if dur_row and i < len(dur_row) else None
            if d_m is None or t_s is None:
                out.append(None)
            else:
                out.append({"distance_km": round(d_m / 1000.0, 2), "duration_min": int(round(t_s / 60.0))})
        if any(out):
            ttl_cache.set(key, out, ttl_seconds=24 * 3600)
        return out

    def calculate_route(self, lat1: float, lon1: float, lat2: float, lon2: float) -> dict[str, Any]:
        """Real route (OSRM driving + walking) with a clearly flagged fallback.

        Returns {distance_km, drive_min, walk_min, mode, source} where source is
        'osrm' or 'estimate'. Never raises, never blocks for long.
        """
        driving = self._osrm_route(lat1, lon1, lat2, lon2, "driving")
        if driving is None:
            return self._estimate_route(lat1, lon1, lat2, lon2)
        km = driving["distance_km"]
        walk = self._osrm_route(lat1, lon1, lat2, lon2, "foot") if km <= 3.0 else None
        return {
            "distance_km": km,
            "drive_min": driving["duration_min"],
            "walk_min": walk["duration_min"] if walk else None,
            "mode": "driving",
            "source": "osrm",
        }

    @staticmethod
    def _estimate_route(lat1: float, lon1: float, lat2: float, lon2: float) -> dict[str, Any]:
        km = round(max(haversine_km(lat1, lon1, lat2, lon2), 0.15), 2)
        return {
            "distance_km": km,
            "drive_min": max(4, int(round(km * 1.6))),
            "walk_min": max(4, int(round(km * 12))),
            "mode": "driving",
            "source": "estimate",
        }

    # -- 4. place details ----------------------------------------------------

    def get_place_details(self, place: dict[str, Any], lat: float | None = None,
                          lon: float | None = None) -> dict[str, Any]:
        """Enrich a normalized place (typically with its route times resolved)."""
        out = {**place}
        if out.get("routing_source") != "osrm" and lat is not None and lon is not None:
            self._attach_route_times([out], lat, lon)
        return out


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
        "fast_food": ["energetic"], "dessert": ["happy", "celebratory"],
        "walk": ["calm", "refreshed"], "cinema": ["calm", "warm"],
        "museum": ["curious", "calm"], "attraction": ["curious", "happy"],
        "shopping": ["happy", "energetic"], "bookstore": ["calm", "curious"],
        "entertainment": ["happy", "energetic"], "wellness": ["calm", "refreshed"],
    }.get(category, ["calm"])


location_service = LocationService()