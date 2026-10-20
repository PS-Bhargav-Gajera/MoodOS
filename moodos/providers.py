from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime
from typing import Any

from moodos.cache import ttl_cache
from moodos.config import settings
from moodos.geo import ProviderUnavailable

import httpx

log = logging.getLogger("moodos.providers")

TIMEOUT = 12.0
HEADERS = {"User-Agent": "MoodOS/0.1 (student project; contact: local)"}

# Section 2 contract, Open-Meteo row: the forecast request gets its own bound
# instead of borrowing TIMEOUT. Same value today, but deliberately NOT shared:
# retuning TIMEOUT for another provider must never silently move this row's
# limit, and the contract test asserts against this name.
OPEN_METEO_TIMEOUT_S = 12.0


def get_weather(lat: float, lon: float, *, strict: bool = False) -> dict[str, Any]:
    key = f"weather:{round(lat, 3)}:{round(lon, 3)}"
    try:
        cached = ttl_cache.get(key)
    except Exception as exc:
        # TTLCache.get writes on eviction and indexes "expires", so it can raise
        # (OSError / KeyError) independently of the network. A dead cache is not
        # a reason to report no weather -- log it and fall through to the fetch.
        log.warning("weather cache read failed for %s: %s", key, exc)
        cached = None
    if cached:
        return cached
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code,precipitation,wind_speed_10m"
    )
    try:
        with httpx.Client(timeout=OPEN_METEO_TIMEOUT_S, headers=HEADERS) as client:
            data = client.get(url).json()
        current = data.get("current") or {}
        # A 200 is not proof of dry weather. Open-Meteo answers error bodies
        # ({"error":..., "reason":...}) with 200 too, and a "current" block of
        # nulls says nothing at all. Raise so the existing failure path below
        # returns the neutral dict (rainy is None) and never caches a payload
        # that would masquerade as "clear, dry, live" for 15 minutes.
        if not current or current.get("weather_code") is None:
            raise ValueError("open-meteo response carried no usable current block")
        code = int(current.get("weather_code") or 0)
        rainy = code in {51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99} or float(
            current.get("precipitation") or 0
        ) > 0
        result = {
            "temperature_c": current.get("temperature_2m"),
            "precipitation": current.get("precipitation"),
            "weather_code": code,
            "condition": _weather_label(code, rainy),
            "rainy": rainy,
            "lat": lat,
            "lon": lon,
            "source": "open-meteo",
            "freshness": "live",
        }
        ttl_cache.set(key, result, ttl_seconds=15 * 60)
        return result
    except Exception:
        if strict:
            raise ProviderUnavailable(
                "open-meteo",
                "Open-Meteo weather is unavailable (timeout or HTTP failure), "
                "so no live conditions can be reported.",
            ) from None
        # Section 2 fallback, Open-Meteo row: "assume neutral weather, add an
        # indoor option". Neutral means rainy stays None, NOT False -- we do
        # not know it is dry -- and indoor_recommended tells the planner to
        # carry one indoor step so a wet evening is still covered.
        return {
            "temperature_c": None,
            "rainy": None,
            "condition": "unknown",
            "source": "unavailable",
            "freshness": "unknown",
            "error": "open-meteo unavailable",
            "indoor_recommended": True,
            "lat": lat,
            "lon": lon,
        }


def _weather_label(code: int, rainy: bool) -> str:
    if rainy or code in {51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99}:
        return "rain"
    if code == 0:
        return "clear"
    if code in {1, 2, 3}:
        return "cloudy"
    if code in {45, 48}:
        return "fog"
    if code in {71, 73, 75, 77}:
        return "snow"
    return "mixed"


def reverse_geocode(lat: float, lon: float) -> dict[str, Any]:
    key = f"rev:{round(lat, 4)}:{round(lon, 4)}"
    cached = ttl_cache.get(key)
    if cached:
        return cached
    url = f"{settings.nominatim_url.rstrip('/')}/reverse"
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
            data = client.get(
                url,
                params={"lat": lat, "lon": lon, "format": "jsonv2", "addressdetails": 1},
            ).json()
        addr = data.get("address") or {}
        cc = (addr.get("country_code") or "").lower()
        # OSM address roles vary by region (e.g. in India the real city can live
        # in `state_district` as "Ahmedabad" while `village` holds a locality).
        # Use a single robust priority: the most specific readable city first.
        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("state_district")
            or addr.get("county")
            or addr.get("municipality")
            or addr.get("village")
        )
        # Area = the genuine neighborhood / locality level only (suburb + locality).
        # Deliberately exclude coarse buckets (city_district / borough / quarter)
        # so we don't render long garbled strings.
        village = addr.get("village")
        area = ", ".join(
            part
            for part in (
                addr.get("suburb"),
                village if village and village != city else None,
                addr.get("neighbourhood"),
                addr.get("locality"),
            )
            if part
        ).strip()
        result = {
            "display_name": data.get("display_name"),
            "city": city,
            "area": area,
            "suburb": addr.get("suburb") or addr.get("neighbourhood"),
            "state": addr.get("state"),
            "country": addr.get("country"),
            "country_code": cc,
            "lat": lat,
            "lon": lon,
            "source": "nominatim-reverse",
        }
        ttl_cache.set(key, result, ttl_seconds=6 * 3600)
        return result
    except Exception:
        return {
            "city": None,
            "area": "",
            "state": None,
            "country": None,
            "country_code": "",
            "lat": lat,
            "lon": lon,
            "source": "unavailable",
        }


def nearby_places(lat: float, lon: float, query: str = "cafe", limit: int = 8) -> list[dict]:
    key = f"places:{round(lat, 3)}:{round(lon, 3)}:{query}"
    cached = ttl_cache.get(key)
    if cached:
        return cached
    amenity = "cafe" if "cafe" in query.lower() or "coffee" in query.lower() else "restaurant"
    if "park" in query.lower() or "walk" in query.lower():
        amenity = "park"
    places = _overpass_nearby(lat, lon, amenity, limit=limit)
    if not places:
        places = _nominatim_nearby(lat, lon, query, limit=limit)
    ttl_cache.set(key, places, ttl_seconds=20 * 60)
    return places


_OVERPASS_STATE: dict[str, Any] = {
    "consecutive_failures": 0,
    "open_until": 0.0,
}


def _overpass_mirrors() -> tuple[str, ...]:
    """Primary first, then the configured fallbacks, deduped.

    Env-overridable so a self-hosted or paid instance can be swapped in
    without touching code -- the public one is unreliable enough that the
    plan endpoint cannot depend on it alone.
    """
    urls = [settings.overpass_url]
    urls.extend(u.strip() for u in str(settings.overpass_mirrors or "").split(","))
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            ordered.append(url)
    return tuple(ordered)


def _overpass_breaker_open() -> bool:
    """True while the breaker is open, i.e. OSM should not be called at all."""
    if time.time() < _OVERPASS_STATE["open_until"]:
        return True
    if _OVERPASS_STATE["open_until"]:
        # Cooldown elapsed: let one query through to probe.
        log.info("overpass breaker half-open, probing again")
        _OVERPASS_STATE["open_until"] = 0.0
        _OVERPASS_STATE["consecutive_failures"] = 0
    return False


def _overpass_record_ok() -> None:
    _OVERPASS_STATE["consecutive_failures"] = 0
    _OVERPASS_STATE["open_until"] = 0.0


def _overpass_record_failure() -> None:
    n = int(_OVERPASS_STATE["consecutive_failures"]) + 1
    _OVERPASS_STATE["consecutive_failures"] = n
    if n >= int(settings.overpass_trip_after):
        cooldown = float(settings.overpass_cooldown_s)
        _OVERPASS_STATE["open_until"] = time.time() + cooldown
        log.warning(
            "overpass breaker OPEN after %s consecutive failures; "
            "skipping OSM for %.1fs",
            n,
            cooldown,
        )


_OVERPASS_LOCK = threading.Lock()
_OVERPASS_LAST_CALL: float = 0.0


def reset_overpass_breaker() -> None:
    """Test hook: forget any recorded failures."""
    _OVERPASS_STATE["consecutive_failures"] = 0
    _OVERPASS_STATE["open_until"] = 0.0
    global _OVERPASS_LAST_CALL
    _OVERPASS_LAST_CALL = 0.0


def _overpass_query(query: str) -> dict | None:
    """POST an Overpass QL query within a hard time budget. Returns None on failure.

    Three things keep a flaky public OSM from stalling the whole request:

      * a total wall-clock budget across every mirror and retry
        (``settings.overpass_budget_s``) -- not a per-attempt timeout times N;
      * a circuit breaker that stops calling OSM at all once it has failed
        ``settings.overpass_trip_after`` queries in a row;
      * a single choke point, so every OSM leg in this module inherits the same
        protection instead of each hardcoding its own URL.

    Returns the parsed body, or None.
    """
    global _OVERPASS_LAST_CALL
    with _OVERPASS_LOCK:
        if _overpass_breaker_open():
            log.info("overpass query skipped: breaker is open")
            return None

        deadline = time.monotonic() + float(settings.overpass_budget_s)
        last: str = "no mirror attempted"
        min_gap_ms = getattr(settings, "osm_min_interval_ms", 1500)
        if min_gap_ms in (None, 900):
            min_gap_ms = 1500
        min_gap_s = float(min_gap_ms) / 1000.0
        # In fast-budget test environments, bound the throttle to avoid starving the budget
        if float(settings.overpass_budget_s) < min_gap_s:
            min_gap_s = max(0.0, float(settings.overpass_budget_s) * 0.25)

        for mirror in _overpass_mirrors():
            for attempt in range(2):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    log.warning(
                        "overpass budget of %.1fs exhausted before %s (attempt %s)",
                        float(settings.overpass_budget_s), mirror, attempt + 1,
                    )
                    _overpass_record_failure()
                    return None

                wait = (_OVERPASS_LAST_CALL + min_gap_s) - time.monotonic()
                if wait > 0:
                    log.info(
                        "overpass rate limit throttle: sleeping %.3fs to respect min interval %.3fs",
                        wait, min_gap_s,
                    )
                    time.sleep(wait)

                try:
                    with httpx.Client(
                        timeout=min(float(settings.overpass_timeout_s), remaining),
                        headers=HEADERS,
                    ) as client:
                        resp = client.post(mirror, content=query)
                    _OVERPASS_LAST_CALL = time.monotonic()
                    if resp.status_code == 200:
                        _overpass_record_ok()
                        return resp.json()
                    last = "HTTP %s" % resp.status_code
                    if resp.status_code == 429:
                        raw_ra = resp.headers.get("Retry-After")
                        try:
                            ra = float(raw_ra) if raw_ra else 5.0
                        except (ValueError, TypeError):
                            ra = 5.0
                        sleep_s = min(max(ra, 0.0), 10.0)
                        log.warning(
                            "overpass %s -> 429 Too Many Requests; backing off %.1fs (Retry-After=%s)",
                            mirror, sleep_s, raw_ra,
                        )
                        nap = min(sleep_s, max(0.0, deadline - time.monotonic()))
                        if nap > 0:
                            time.sleep(nap)
                        continue
                    if resp.status_code not in (502, 503, 504):
                        log.warning("overpass %s -> %s", mirror, last)
                        break
                except Exception as exc:
                    _OVERPASS_LAST_CALL = time.monotonic()
                    last = type(exc).__name__
                    log.warning(
                        "overpass %s attempt %s failed: %s", mirror, attempt + 1, exc
                    )
                # Back off, but never sleep past the budget.
                nap = min(1.2 * (attempt + 1), deadline - time.monotonic())
                if nap > 0:
                    time.sleep(nap)
        _overpass_record_failure()
        log.warning("overpass query gave up: %s", last)
        return None


def _overpass_walk_spots(lat: float, lon: float, limit: int = 8) -> list[dict]:
    """Real, NAMED outdoor places to walk in, from the OSM map.

    Parks alone are too sparse in dense Indian cities to reliably yield a
    result, so we also accept public gardens, pedestrian streets and named
    green/park areas. Only elements carrying a real OSM `name` are returned —
    an unnamed polygon cannot be presented to the user as a real place.
    """
    key = f"walkspot:{round(lat, 3)}:{round(lon, 3)}"
    cached = ttl_cache.get(key)
    if cached is not None:
        return cached
    query = f"""
    [out:json][timeout:15];
    (
      way(around:2500,{lat},{lon})["leisure"~"^(park|garden)$"];
      node(around:2500,{lat},{lon})["leisure"~"^(park|garden)$"];
      way(around:2500,{lat},{lon})["highway"="pedestrian"]["name"];
      way(around:2500,{lat},{lon})["leisure"="nature_reserve"]["name"];
      way(around:2500,{lat},{lon})["landuse"="recreation_ground"]["name"];
    );
    out center {limit * 3};
    """
    spots: list[dict] = []
    data = _overpass_query(query)
    if data is None:
        ttl_cache.set(key, [], ttl_seconds=5 * 60)
        return []
    for el in data.get("elements") or []:
        tags = el.get("tags") or {}
        name = tags.get("name") or tags.get("name:en")
        if not name:
            continue
        plat = el.get("lat") or (el.get("center") or {}).get("lat")
        plon = el.get("lon") or (el.get("center") or {}).get("lon")
        if plat is None or plon is None:
            continue
        leisure = tags.get("leisure") or ""
        if tags.get("highway") == "pedestrian":
            label = f"{name} (pedestrian street)"
        elif leisure == "nature_reserve":
            label = f"{name} (green space)"
        elif leisure == "garden":
            label = f"{name} garden"
        elif tags.get("landuse") == "recreation_ground":
            label = f"{name} recreation ground"
        else:
            label = f"{name} park"
        spots.append({
            "id": f"osm-walk:{el.get('type')}:{el.get('id')}",
            "title": label,
            "name": name,
            "kind": "place",
            "subtype": "walk",
            "lat": float(plat),
            "lon": float(plon),
            "text": f"Walkable open space: {name} ({leisure or tags.get('highway') or 'green space'})",
            "estimated_cost": 0,
            "duration_min": 20,
            "intensity": "low",
            "outdoor": True,
            "needs_clear_weather": True,
            "source": "overpass",
        })
        if len(spots) >= limit:
            break
    ttl_cache.set(key, spots, ttl_seconds=30 * 60)
    return spots


def nearby_walks(lat: float, lon: float, limit: int = 5) -> list[dict]:
    key = f"walks:{round(lat, 3)}:{round(lon, 3)}"
    cached = ttl_cache.get(key)
    if cached is not None:
        return cached
    spots = _overpass_walk_spots(lat, lon, limit=limit)
    if not spots:
        # Fall back to the amenity-based lookup already used for general POIs.
        spots = _overpass_nearby(lat, lon, "park", limit=limit)
    ttl_cache.set(key, spots, ttl_seconds=30 * 60)
    return spots


def nearby_cinemas(lat: float, lon: float, limit: int = 6, *,
                   strict: bool = False) -> list[dict]:
    """Find real cinema/theatre venues near the user from the OSM map."""
    from moodos.location_service import location_service

    places = location_service.search_nearby_places(
        lat, lon, categories="cinema", radius_m=15000, limit=limit, strict=strict,
    )
    venues = []
    for p in places:
        name = p.get("name") or p.get("title")
        if not name:
            continue
        venues.append(
            {
                **p,
                "id": p.get("id") or f"cinema-osm:{p.get('source_id')}",
                "title": f"{name} cinema",
                "name": name,
                "kind": "movie",
                "venue": True,
                "text": f"Movie theatre: {name}",
                "source": p.get("source") or "overpass-cinema",
                "estimated_cost": p.get("estimated_cost") or 250,
                "duration_min": 140,
                "intensity": "low",
                "review_quality": p.get("review_quality") or 7.0,
                "has_venue": True,
            }
        )
    return venues


MOOD_CUISINE_MAP: dict[str, dict[str, Any]] = {
    "calm": {"cuisines": ["tea", "bakery", "coffee_shop"], "amenities": ["cafe"], "vibe": "quiet"},
    "relaxed": {"cuisines": ["tea", "bakery", "coffee_shop"], "amenities": ["cafe"], "vibe": "quiet"},
    "happy": {"cuisines": ["multi-cuisine", "italian", "chinese", "indian"], "amenities": ["restaurant"], "vibe": "lively"},
    "celebratory": {"cuisines": ["fine_dining", "multi-cuisine", "italian"], "amenities": ["restaurant"], "vibe": "upscale"},
    "comfort": {"cuisines": ["indian", "pizza", "burger", "biryani"], "amenities": ["restaurant", "fast_food"], "vibe": "cozy"},
    "healthy": {"cuisines": ["salad", "vegan", "health_food", "juice"], "amenities": ["restaurant", "cafe"], "vibe": "fresh"},
    "romantic": {"cuisines": ["italian", "french", "fine_dining", "continental"], "amenities": ["restaurant"], "vibe": "intimate"},
    "date": {"cuisines": ["italian", "french", "continental", "multi-cuisine"], "amenities": ["restaurant"], "vibe": "intimate"},
    "energetic": {"cuisines": ["burger", "pizza", "mexican", "american"], "amenities": ["restaurant", "fast_food"], "vibe": "fun"},
    "stressed": {"cuisines": ["tea", "bakery", "ice_cream"], "amenities": ["cafe"], "vibe": "soothing"},
    "adventurous": {"cuisines": ["japanese", "thai", "korean", "mexican", "lebanese"], "amenities": ["restaurant"], "vibe": "exotic"},
}


_INSTITUTIONAL_MARKERS = (
    "canteen", "can-teen", "cafeteria", "institution", "institutional",
    "mess", "staff", "employee", "workforce", "hostel", "dorm",
    "school", "college", "university", "campus", "faculty", "student",
    "factory", "office", "employees", "staffroom", "dairy parlour internal",
)


def _institutional_flag(tags: dict, name: str) -> str | None:
    """Return a reason string when a venue looks like an internal / campus /
    staff-only canteen that isn't a good public 'treat' pick, else None."""
    blob = f"{name or ''} {tags.get('operator') or ''} {tags.get('operator:type') or ''} {tags.get('name:en') or ''}".lower()
    access = (tags.get("access") or "").lower()
    amenity = (tags.get("amenity") or "").lower()
    cuisine = (tags.get("cuisine") or "").lower()
    if access in {"private", "no"}:
        return "access marked private/not public"
    if amenity in {"school_canteen", "kindergarten", "school"}:
        return "school/campus canteen, not open to the public"
    if any(m in blob for m in _INSTITUTIONAL_MARKERS):
        marker = next(m for m in _INSTITUTIONAL_MARKERS if m in blob)
        return f"internal {marker} venue (likely staff/campus-only)"
    if "fast_food" in amenity and any(m in cuisine for m in ("institution", "canteen", "college", "school")):
        return f"institutional fast-food ({cuisine})"
    return None


def _estimate_food_cost(tags: dict, name: str, amenity_type: str) -> tuple[int, str]:
    """Best-effort per-venue-type price INR tier. OSM rarely carries real prices,
    so this is a rough estimate derived from tags/venue type (never a flat default).
    Returns (cost_inr, price_tier)."""
    blob = f"{name or ''} {tags.get('operator') or ''}".lower()
    # Explicit pricing tags win when present.
    try:
        stars = int(tags.get("stars") or 0)
        if stars >= 4:
            return 900, "premium"
        if stars == 3:
            return 600, "mid"
    except (TypeError, ValueError):
        pass
    price = str(tags.get("price") or tags.get("price:range") or "")
    ps = price.replace("₹", "").replace("Rs", "").strip()
    if "₹" in price or (ps[:1].isdigit()):
        try:
            n = int(re.split(r"[-–&].", ps)[0].strip()[:1])
            if n and 1 <= n <= 4:
                return {1: 150, 2: 300, 3: 600, 4: 1000}[n], "premium" if n >= 4 else ("mid" if n >= 3 else "budget")
        except (TypeError, ValueError, IndexError):
            ps = ""  # fall through to heuristic below on unparseable price
    fine = any(w in blob for w in ("hotel", "grand", "palace", "fine", "5 star", "resort", "luxury"))
    quick = amenity_type in {"fast_food", "ice_cream", "farsan"} or any(
        w in blob for w in ("farsan", "snacks", "dairy", "parlour", "canteen", "stall", "kiosk", "tiffin")
    )
    cafe_like = amenity_type == "cafe" or any(w in blob for w in ("cafe", "coffee", "bakery"))
    if fine:
        return 750, "premium"
    if quick:
        return 150, "budget"
    if cafe_like:
        return 250, "budget"
    # plain sit-down restaurant
    return 450, "mid"


def _opening_hours_is_open(opening_hours: str | None, at_time=None) -> tuple[bool | None, str]:
    """Lightweight opening_hours check for common OSM forms. Returns
    (is_open_or_None, note). None means we couldn't parse / unknown.
    Supports '24/7' and simple 'We HH:MM-HH:MM' day/range rules."""
    if not opening_hours:
        return None, "opening hours not listed"
    s = opening_hours.strip()
    if s.lower() in {"24/7", "24 hours", "always", "open"}:
        return True, "open 24/7"
    now = at_time or datetime.now()
    weekday = now.weekday()  # 0=Mon
    hour = now.hour + now.minute / 60.0
    days = {"mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6}
    matched = False
    for rule in s.split(";"):
        rule = rule.strip()
        if not rule:
            continue
        m = __import__("re").match(r"(?i)([a-z]{2})(?:-([a-z]{2}))?\s+(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", rule)
        if not m:
            continue
        d1, d2, t1, t2 = m.group(1).lower(), (m.group(2) or "").lower(), m.group(3), m.group(4)
        if d1 not in days:
            continue
        if d2:
            d2n = days.get(d2)
            if d2n is None:
                continue
            span = (d2n - days[d1]) % 7
            in_days = (weekday - days[d1]) % 7 <= span if span else weekday == days[d1]
        else:
            in_days = weekday == days[d1]
        if not in_days:
            continue
        matched = True
        try:
            h1, m1 = (int(x) for x in t1.split(":"))
            h2, m2 = (int(x) for x in t2.split(":"))
        except (ValueError, AttributeError):
            continue
        open_t = h1 + m1 / 60.0
        close_t = h2 + m2 / 60.0
        # handle overnight ranges
        if close_t <= open_t:
            close_t += 24
            cur = hour if hour >= open_t else hour + 24
        else:
            cur = hour
        return open_t <= cur < close_t, f"{opening_hours}"
    if not matched:
        return None, f"opening hours unparsed ({opening_hours})"
    return False, f"closed today ({opening_hours})"


def nearby_restaurants(
    lat: float,
    lon: float,
    cuisine: str | None = None,
    dietary: str | None = None,
    radius_m: int = 5000,
    limit: int = 10,
    *,
    strict: bool = False,
) -> list[dict]:
    """Find nearby restaurants from OpenStreetMap with optional cuisine/dietary filters.

    Uses the Overpass API to query for amenity=restaurant with rich tag extraction
    (cuisine, dietary, opening_hours, phone, website, wheelchair access).
    """
    parts = [f"cuisine:{cuisine}" if cuisine else "", f"diet:{dietary}" if dietary else ""]
    key = f"restaurants:{round(lat, 3)}:{round(lon, 3)}:{':'.join(parts)}:{radius_m}"
    cached = ttl_cache.get(key)
    if cached:
        return cached

    cuisine_filter = ""
    if cuisine:
        cuisine_filter = f'["cuisine"~"{cuisine}",i]'
    dietary_filter = ""
    if dietary:
        dietary_filter = f'["diet:{dietary}"="yes"]'

    query = f"""
    [out:json][timeout:15];
    (
      node["amenity"="restaurant"]{cuisine_filter}{dietary_filter}(around:{radius_m},{lat},{lon});
      way["amenity"="restaurant"]{cuisine_filter}{dietary_filter}(around:{radius_m},{lat},{lon});
      node["amenity"="fast_food"]{cuisine_filter}{dietary_filter}(around:{radius_m},{lat},{lon});
      node["amenity"="cafe"]{cuisine_filter}{dietary_filter}(around:{radius_m},{lat},{lon});
      node["amenity"="ice_cream"]{cuisine_filter}{dietary_filter}(around:{radius_m},{lat},{lon});
    );
    out center {limit * 2};
    """
    restaurants: list[dict] = []
    data = _overpass_query(query)
    if not isinstance(data, dict):
        # P1b: Overpass failed (timeout, 502/429, breaker) — try the live
        # fallback provider for the same category before giving up. Lazy
        # import: fallback_places imports this module at load time.
        from moodos.fallback_places import fallback_places
        fb = fallback_places(lat, lon, "restaurant", limit=limit)
        if fb:
            return fb[:limit]
        if strict:
            raise ProviderUnavailable(
                "overpass",
                "Overpass and the fallback provider are both unavailable "
                "(timeout, rate limit or breaker open) — no restaurant data "
                "to return. Not falling back to a stored list.",
            )
        return []
    try:
        for el in data.get("elements") or []:
            tags = el.get("tags") or {}
            plat = el.get("lat") or (el.get("center") or {}).get("lat")
            plon = el.get("lon") or (el.get("center") or {}).get("lon")
            if plat is None or plon is None:
                continue
            name = tags.get("name") or tags.get("brand")
            if not name:
                continue  # no real venue name -> no usable step data
            cuisines = tags.get("cuisine", "").replace(";", ", ")
            amenity_type = tags.get("amenity", "restaurant")

            # Skip internal/campus/staff-only venues — not good public "treat" picks.
            inst_reason = _institutional_flag(tags, name)
            if inst_reason:
                continue

            if amenity_type == "restaurant":
                subtype = "restaurant"
                duration = 60
            elif amenity_type == "cafe":
                subtype = "cafe"
                duration = 45
            elif amenity_type == "fast_food":
                subtype = "fast_food"
                duration = 25
            else:
                subtype = "ice_cream"
                duration = 20

            cost, price_tier = _estimate_food_cost(tags, name, amenity_type)
            open_now, opening_note = _opening_hours_is_open(tags.get("opening_hours"))

            diet_tags = {}
            for t_key, t_val in tags.items():
                if t_key.startswith("diet:") and t_val == "yes":
                    diet_tags[t_key.replace("diet:", "")] = True

            restaurants.append(
                {
                    "id": f"osm-restaurant:{el.get('type')}:{el.get('id')}",
                    "title": name,
                    "kind": "food",
                    "subtype": subtype,
                    "amenity": amenity_type,
                    "cuisine": cuisines or None,
                    "dietary": diet_tags or None,
                    "lat": float(plat),
                    "lon": float(plon),
                    "text": f"{name} — {cuisines}" if cuisines else name,
                    "opening_hours": tags.get("opening_hours"),
                    "opening_note": opening_note,
                    "likely_closed_at": True if open_now is False else None,
                    "phone": tags.get("phone") or tags.get("contact:phone"),
                    "website": tags.get("website") or tags.get("contact:website"),
                    "wheelchair": tags.get("wheelchair"),
                    "operator": tags.get("operator"),
                    "source": "overpass-restaurant",
                    "estimated_cost": cost,
                    "price_tier": price_tier,
                    "price_is_estimate": True,
                    "duration_min": duration,
                    "intensity": "low",
                    "crowded": False,
                    "outdoor": tags.get("outdoor_seating") == "yes",
                    "review_quality": 7.0,
                    "has_venue": True,
                }
            )
            if len(restaurants) >= limit:
                break
        if restaurants:
            ttl_cache.set(key, restaurants, ttl_seconds=20 * 60)
        return restaurants
    except Exception:
        return []


def search_restaurants_by_mood(
    lat: float,
    lon: float,
    mood: str,
    dietary: str | None = None,
    radius_m: int = 5000,
    limit: int = 10,
    *,
    strict: bool = False,
) -> list[dict]:
    """Find restaurants that match a user's mood by mapping mood to cuisine preferences."""
    mood_lower = mood.lower().strip()
    mapping = MOOD_CUISINE_MAP.get(mood_lower, MOOD_CUISINE_MAP.get("happy", {}))
    cuisines = mapping.get("cuisines", [])
    vibe = mapping.get("vibe", "")

    all_results: list[dict] = []
    seen_ids: set[str] = set()
    provider_error: ProviderUnavailable | None = None

    # Try each preferred cuisine, collect results (bounded to keep latency low)
    for cuisine in cuisines[:2]:
        try:
            results = nearby_restaurants(lat, lon, cuisine=cuisine, dietary=dietary,
                                         radius_m=radius_m, limit=5, strict=strict)
        except ProviderUnavailable as exc:
            provider_error = exc
            break
        for r in results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                r["mood_match"] = mood_lower
                r["mood_vibe"] = vibe
                all_results.append(r)
        if len(all_results) >= limit:
            break

    # Generic nearby restaurants as filler if we still have room. Same live
    # provider, never a stored list -- and a failure here must not erase
    # results we already hold, so it is never strict.
    if len(all_results) < limit:
        try:
            generic = nearby_restaurants(lat, lon, dietary=dietary, radius_m=radius_m,
                                         limit=limit)
        except ProviderUnavailable:
            generic = []
        for r in generic:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                r["mood_match"] = mood_lower
                r["mood_vibe"] = vibe
                all_results.append(r)
            if len(all_results) >= limit:
                break

    if not all_results and provider_error is not None:
        raise provider_error
    return all_results[:limit]


def _overpass_nearby(lat: float, lon: float, amenity: str, limit: int = 8) -> list[dict]:
    if amenity == "park":
        filt = '["leisure"="park"]'
        subtype = "walk"
        outdoor = True
        cost = 0
        duration = 20
    else:
        filt = f'["amenity"="{amenity}"]'
        subtype = "cafe" if amenity == "cafe" else "food"
        outdoor = False
        cost = 250
        duration = 45
    query = f"""
    [out:json][timeout:12];
    (
      node{filt}(around:4000,{lat},{lon});
      way{filt}(around:4000,{lat},{lon});
    );
    out center {limit};
    """
    try:
        data = _overpass_query(query) or {}
        places = []
        for el in data.get("elements") or []:
            tags = el.get("tags") or {}
            plat = el.get("lat") or (el.get("center") or {}).get("lat")
            plon = el.get("lon") or (el.get("center") or {}).get("lon")
            if plat is None or plon is None:
                continue
            name = tags.get("name") or tags.get("brand")
            if not name:
                continue  # no real venue name -> no usable step data
            if amenity != "park":
                inst_reason = _institutional_flag(tags, name)
                if inst_reason:
                    continue
                cost, price_tier = _estimate_food_cost(tags, name, amenity)
            else:
                price_tier = None
            open_now, opening_note = (_opening_hours_is_open(tags.get("opening_hours"))
                                      if amenity != "park" else (None, ""))
            places.append(
                {
                    "id": f"osm:{el.get('type')}:{el.get('id')}",
                    "title": name,
                    "kind": "place",
                    "subtype": subtype,
                    "lat": float(plat),
                    "lon": float(plon),
                    "text": f"{name} {tags.get('cuisine', '')} {amenity}".strip(),
                    "opening_hours": tags.get("opening_hours"),
                    "opening_note": opening_note,
                    "likely_closed_at": True if open_now is False and amenity != "park" else None,
                    "source": "overpass",
                    "estimated_cost": cost,
                    "price_tier": price_tier,
                    "price_is_estimate": amenity != "park",
                    "duration_min": duration,
                    "intensity": "low",
                    "crowded": False,
                    "outdoor": outdoor,
                    "needs_clear_weather": outdoor,
                }
            )
            if len(places) >= limit:
                break
        return places
    except Exception:
        return []


def _nominatim_nearby(lat: float, lon: float, query: str, limit: int) -> list[dict]:
    delta = 0.04
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": str(limit),
        "viewbox": f"{lon - delta},{lat + delta},{lon + delta},{lat - delta}",
        "bounded": "1",
    }
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
            rows = client.get("https://nominatim.openstreetmap.org/search", params=params).json()
        places = []
        for row in rows:
            name = row.get("display_name", "").split(",")[0]
            tags = {"operator": "", "name": name}
            if _institutional_flag(tags, name):
                continue
            places.append(
                {
                    "id": f"osm:{row.get('place_id')}",
                    "title": name,
                    "kind": "place",
                    "subtype": "cafe",
                    "lat": float(row.get("lat", lat)),
                    "lon": float(row.get("lon", lon)),
                    "text": row.get("display_name", ""),
                    "opening_hours": None,
                    "opening_note": "opening hours not listed",
                    "source": "nominatim",
                    "estimated_cost": 250,
                    "price_tier": "budget",
                    "price_is_estimate": True,
                    "duration_min": 45,
                    "intensity": "low",
                    "crowded": False,
                    "outdoor": False,
                }
            )
        return places
    except Exception:
        return []


def search_books(query: str, limit: int = 5) -> list[dict]:
    key = f"books:{query}"
    cached = ttl_cache.get(key)
    if cached:
        return cached
    url = "https://www.googleapis.com/books/v1/volumes"
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
            data = client.get(url, params={"q": query, "maxResults": limit}).json()
        items = []
        for item in data.get("items") or []:
            info = item.get("volumeInfo") or {}
            items.append(
                {
                    "id": f"book:{item.get('id')}",
                    "title": info.get("title", "Untitled"),
                    "kind": "book",
                    "text": (info.get("description") or "")[:600],
                    "themes": info.get("categories") or [],
                    "source": "google-books",
                    "estimated_cost": 0,
                    "duration_min": 0,
                    "intensity": "low",
                }
            )
        ttl_cache.set(key, items, ttl_seconds=6 * 3600)
        return items
    except Exception:
        return []


def search_music(query: str, limit: int = 5, country: str = "IN", seed: int = 0) -> list[dict]:
    """Live Spotify search — the single source of music truth.

    There is deliberately NO iTunes/seed fallback: an invented or generic
    catalogue entry is worse than an honest empty list, and every track we
    surface must be playable on the user's own Spotify account.
    """
    key = f"music:{query}|{country}|seed={seed}"
    cached = ttl_cache.get(key)
    if cached:
        return cached
    from moodos import spotify as spotify_api

    tracks = spotify_api.search_tracks(query, limit=limit, market=country, offset=seed * limit)
    # Only cache a non-empty result. An empty list is ambiguous: it is either a
    # genuine no-match OR a dead/rate-limited Spotify, and caching the latter
    # for 20 minutes turns one transient failure into a half-hour of silence.
    if tracks:
        ttl_cache.set(key, tracks, ttl_seconds=20 * 60)
    return tracks


def _movie_year(release_date: str | None) -> int | None:
    """Extract a 4-digit year from a TMDB release_date, or None."""
    if not release_date:
        return None
    try:
        return int(str(release_date)[:4])
    except (TypeError, ValueError):
        return None


def _disambiguate_movie(
    hits: list[dict],
    query_title: str,
    hint_year: int | None = None,
    hint_language: str | None = None,
) -> dict | None:
    """Pick the single most likely TMDB result for a title being shown at a
    cinema, so a same-title mismatch never silently yields the wrong runtime.

    Rules:
      * Only candidates whose title matches (case-insensitive) the query count —
        never a random first-ish hit with a different title.
      * Prefer a candidate that actually HAS a runtime and a release year
        (the real theatrical film) over low-info duplicates.
      * When a cinema hint is given (year / language of what's showing), boost
        candidates that match; penalize clear mismatches.
      * Tie-break by popularity / vote_count (the well-known release wins).

    Returns the best hit, or None when nothing passes a basic confidence check.
    """
    q = str(query_title or "").strip().lower()
    if not q:
        return None
    best = None
    best_score = -1.0
    best_reason = "no usable hits"
    for m in hits or []:
        mt = str(m.get("title") or "").strip().lower()
        if mt != q:
            continue  # title must match; never fall back to a wrong-title film
        score = 0.0
        reason = []
        year = _movie_year(m.get("release_date"))
        runtime = m.get("duration_min")
        if runtime:
            score += 1.0
            reason.append(f"runtime={runtime}")
        if m.get("tmdb_id"):
            score += 0.5
        if year:
            score += 0.4
            reason.append(f"year={year}")
        if hint_year and year:
            score += 2.0 if year == hint_year else -1.0
            reason.append(f"year-hint={hint_year}:{'match' if year == hint_year else 'mismatch'}")
        lang = str(m.get("original_language") or "").lower().strip()
        if hint_language and lang:
            score += 1.0 if lang == hint_language.lower() else -1.0
            reason.append(f"lang-hint={hint_language}:{lang}")
        popularity = float(m.get("popularity") or 0.0)
        votes = int(m.get("vote_count") or 0)
        if popularity or votes:
            score += 0.1 * min(popularity / 100.0, 1.0) + 0.1 * min(votes / 1000.0, 1.0)
        if score > best_score:
            best_score = score
            best = m
            best_reason = " + ".join(reason) or "title match only"
    if best is None:
        log.warning("tmdb disambiguate failed for %r: %s", query_title, best_reason)
        return None
    log.info("tmdb disambiguate '%s' -> id=%s (%s) score=%.2f",
             query_title, best.get("tmdb_id"), best_reason, best_score)
    return best


def _disambiguation_confident(hit: dict | None, query_title: str) -> bool:
    """Basic confidence gate. A hit is only trusted when it's an exact-title
    match that carries a TMDB id and a real runtime (or at least a release
    year). If we can't clear this bar we report 'estimate/unverified' rather
    than silently producing a wrong runtime."""
    if not hit:
        return False
    if not hit.get("tmdb_id"):
        return False
    if not hit.get("duration_min") and not hit.get("release_date"):
        log.warning("tmdb low-confidence for %r (id=%s): no runtime or year",
                    query_title, hit.get("tmdb_id"))
        return False
    return True


def _tmdb_movie_from_row(row: dict, watch_at_home: bool = False, source: str = "tmdb") -> dict:
    tmdb_id = row.get("id")
    movie = {
        "id": f"{source}:{tmdb_id}",
        "tmdb_id": tmdb_id,
        "title": row.get("title") or row.get("name"),
        "original_title": row.get("original_title") or "",
        "original_language": (row.get("original_language") or "").lower(),
        "year": _movie_year(row.get("release_date")),
        "popularity": float(row.get("popularity") or 0.0),
        "vote_count": int(row.get("vote_count") or 0),
        "kind": "movie",
        "text": row.get("overview") or "",
        "source": source,
        "estimated_cost": 0 if watch_at_home else 220,
        "duration_min": None,
        "runtime_source": "estimate",
        "intensity": "low",
        "vote": row.get("vote_average"),
        "poster_url": f"https://image.tmdb.org/t/p/w342{row['poster_path']}" if row.get("poster_path") else None,
        "release_date": row.get("release_date"),
        "genre_ids": row.get("genre_ids") or [],
        "watch_at_home": watch_at_home,
    }
    if watch_at_home:
        movie["subtype"] = "streaming"
        movie["estimated_cost"] = 0
    return movie


def search_movies_tmdb(query: str, limit: int = 6, watch_at_home: bool = False,
                       language: str | None = None) -> list[dict]:
    """Search movies on TMDB. Language is a TMDB 2-letter original-language code
    (e.g. 'hi'); search/movie does not accept with_original_language, so we
    filter locally and fill from discover/now-playing when the query is thin."""
    if not settings.tmdb_api_key:
        return []
    key = f"tmdb:{query}:home={watch_at_home}:lang={language or ''}"
    cached = ttl_cache.get(key)
    if cached:
        return cached
    data = _tmdb_json("search/movie", {"query": query, "include_adult": "false"})
    movies = [_tmdb_movie_from_row(row, watch_at_home) for row in (data.get("results") or [])]
    if language:
        filtered = [m for m in movies if m.get("original_language") == language.lower()]
        movies = filtered or movies
    if len(movies) < limit:
        extra = tmdb_discover_movies(
            language=language, watch_at_home=watch_at_home, limit=limit
        )
        seen = {m.get("tmdb_id") for m in movies}
        for item in extra:
            if item.get("tmdb_id") not in seen:
                movies.append(item)
                seen.add(item.get("tmdb_id"))
    movies = movies[:limit]
    for movie in movies:
        runtime_min = _tmdb_runtime_min(movie.get("tmdb_id"))
        if runtime_min:
            movie["duration_min"] = runtime_min
            movie["runtime_source"] = "tmdb"
        elif watch_at_home:
            movie["duration_min"] = 0
    if movies:
        ttl_cache.set(key, movies, ttl_seconds=6 * 3600)
    return movies


def tmdb_now_playing(region: str = "IN", limit: int = 8, watch_at_home: bool = False) -> list[dict]:
    """Films currently in theatres for a region (free TMDB now_playing)."""
    if not settings.tmdb_api_key:
        return []
    region = (region or "IN").upper()
    key = f"tmdb-now:{region}:home={watch_at_home}:{limit}"
    cached = ttl_cache.get(key)
    if cached:
        return cached
    data = _tmdb_json("movie/now_playing", {"region": region, "page": 1})
    movies = [
        _tmdb_movie_from_row(row, watch_at_home, source="tmdb-now-playing")
        for row in (data.get("results") or [])
    ][:limit]
    if movies:
        ttl_cache.set(key, movies, ttl_seconds=3 * 3600)
    return movies


def tmdb_discover_movies(
    language: str | None = None,
    genre_ids: list[int] | None = None,
    region: str = "IN",
    watch_at_home: bool = False,
    limit: int = 8,
) -> list[dict]:
    """Mood/language-biased catalogue via TMDB discover (free)."""
    if not settings.tmdb_api_key:
        return []
    region = (region or "IN").upper()
    gkey = ",".join(str(g) for g in (genre_ids or []))
    key = f"tmdb-disc:{region}:{language or ''}:{gkey}:home={watch_at_home}:{limit}"
    cached = ttl_cache.get(key)
    if cached:
        return cached
    params: dict[str, Any] = {
        "include_adult": "false",
        "sort_by": "popularity.desc",
        "region": region,
        "watch_region": region,
    }
    if language:
        params["with_original_language"] = language
    if genre_ids:
        params["with_genres"] = "|".join(str(g) for g in genre_ids)
    data = _tmdb_json("discover/movie", params)
    movies = [
        _tmdb_movie_from_row(row, watch_at_home, source="tmdb-discover")
        for row in (data.get("results") or [])
    ][:limit]
    if movies:
        ttl_cache.set(key, movies, ttl_seconds=6 * 3600)
    return movies


def tmdb_movie_details(tmdb_id: int) -> dict:
    """Get detailed info for a single movie: runtime, genres, tagline, cast preview."""
    if not settings.tmdb_api_key:
        return {}
    key = f"tmdb-detail:{tmdb_id}"
    cached = ttl_cache.get(key)
    if cached:
        return cached
    data = _tmdb_json(f"movie/{tmdb_id}", {"append_to_response": "credits"})
    if not data.get("title"):
        return {}
    genres = [g.get("name") for g in (data.get("genres") or [])]
    cast = [c.get("name") for c in ((data.get("credits") or {}).get("cast") or [])[:5]]
    result = {
        "tmdb_id": tmdb_id,
        "title": data.get("title"),
        "tagline": data.get("tagline"),
        "overview": data.get("overview"),
        "runtime_min": data.get("runtime"),
        "genres": genres,
        "cast": cast,
        "vote_average": data.get("vote_average"),
        "release_date": data.get("release_date"),
        "poster_url": f"https://image.tmdb.org/t/p/w342{data['poster_path']}" if data.get("poster_path") else None,
        "source": "tmdb-detail",
    }
    ttl_cache.set(key, result, ttl_seconds=24 * 3600)
    return result


def _tmdb_runtime_min(tmdb_id: int) -> int | None:
    """Real runtime (minutes) for a TMDB id, or None when no key / unknown."""
    if not settings.tmdb_api_key or not tmdb_id:
        return None
    return tmdb_movie_details(tmdb_id).get("runtime_min")


def movie_metadata_by_title(
    title: str,
    hint_year: int | None = None,
    hint_language: str | None = None,
) -> dict:
    """Resolve REAL metadata for a movie by title via TMDB: runtime, genres,
    tagline and overview (search + details).

    Multiple search results are requested and the best candidate is picked via
    `_disambiguate_movie`, preferring an exact-title match that has a real
    runtime/year (and matching the cinema hint when provided). If no candidate
    passes the confidence gate, the result is explicitly marked
    'estimate'/'unknown' — we never silently let a same-title mismatch produce a
    wrong runtime. The matched TMDB id is logged for debuggability.
    """
    if not settings.tmdb_api_key:
        return {
            "runtime_min": None, "source": "estimate", "tmdb_id": None,
            "genres": [], "genre_source": "unknown", "tagline": "", "overview": "",
        }
    key = f"tmdb-meta:{str(title).strip().lower()}:{hint_year or ''}:{hint_language or ''}"
    cached = ttl_cache.get(key)
    if cached:
        return cached
    try:
        hits = search_movies_tmdb(str(title), limit=8)
    except Exception:
        hits = []
    best = _disambiguate_movie(hits, str(title), hint_year, hint_language)
    confident = _disambiguation_confident(best, str(title))
    tmdb_id = (best.get("tmdb_id") if best else None) if confident else None
    runtime_min = _tmdb_runtime_min(tmdb_id) if tmdb_id else None
    detail = tmdb_movie_details(tmdb_id) if tmdb_id else {}
    result = {
        "matched_title": (best.get("title") if best else None),
        "runtime_min": runtime_min,
        "source": "tmdb" if runtime_min else "estimate",
        "tmdb_id": tmdb_id,
        "genres": detail.get("genres") or [],
        "tagline": detail.get("tagline") or "",
        "overview": detail.get("overview") or ((best.get("text") or "") if best else ""),
        "genre_source": "tmdb" if (tmdb_id and detail) else "unknown",
        "confidence": "verified" if confident else "estimate",
    }
    if runtime_min or result["genres"]:
        ttl_cache.set(key, result, ttl_seconds=24 * 3600)
    return result


def movie_runtime_by_title(title: str, hint_year: int | None = None, hint_language: str | None = None) -> dict:
    """Resolve a REAL runtime for a movie by title via TMDB (search + details).

    Falls back to an explicit result marked 'estimate' (with no runtime) when no
    TMDB API key is configured, or when disambiguation can't pass the confidence
    gate — so callers can never present a fabricated runtime as fact.
    """
    meta = movie_metadata_by_title(title, hint_year=hint_year, hint_language=hint_language)
    return {
        "runtime_min": meta.get("runtime_min"),
        "source": meta.get("source"),
        "tmdb_id": meta.get("tmdb_id"),
    }


# Mood-fit: which genres are genuinely relaxing / mood-lifting vs. intense.
# Used to keep a de-stress/calm target from being handed an anxiety-inducing film.
_RELAX_GOOD_GENRES = {
    "comedy", "animation", "family", "romance", "music", "documentary",
    "fantasy", "adventure", "kids", "musical",
}
_RELAX_POOR_GENRES = {
    "thriller", "horror", "war", "crime", "mystery", "action",
    "tv movie", "mystery", "noir",
}
_INTENSE_KEYWORDS = (
    "intense", "disturbing", "dark", "traumatic", "abusive", "abuse",
    "grief", "anxiety", "psycholog", "violen", "brutal", "suspense",
    "terror", "death", "murder", "hostage", "suicid", "toxic",
)


def classify_movie_fit(genres: list[str], overview: str = "", tagline: str = "") -> tuple[str, str]:
    """Classify whether a film's tone fits a calm / de-stress / relaxed target.

    Returns ("good" | "neutral" | "poor", reason). Drama is ambiguous, so its
    tone is judged from the overview/tagline keywords (a gentle feel-good drama
    differs from a psychologically intense one like Whiplash).
    """
    gl = {g.strip().lower() for g in (genres or [])}
    text = f"{overview or ''} {tagline or ''}".lower()
    poor_hit = next((g for g in gl if g in _RELAX_POOR_GENRES), None)
    intense = next((k for k in _INTENSE_KEYWORDS if k in text), None)
    if poor_hit:
        return "poor", f"{poor_hit.capitalize()} isn't a de-stress fit for a calm/relaxed target"
    if intense:
        return "poor", f"overview is marked psychologically intense ('{intense}') — not a relax fit"
    good_hit = next((g for g in gl if g in _RELAX_GOOD_GENRES), None)
    if good_hit:
        return "good", f"{good_hit.capitalize()} is a light, mood-appropriate fit for a calm/relaxed target"
    if gl:
        return "neutral", f"tone ({', '.join(sorted(gl))}) not clearly light or intense"
    return "neutral", "genre metadata unavailable"


TMDB_BUDGET_S = 6.0


def _tmdb_json(path: str, params: dict, attempts: int = 12) -> dict:
    """GET api.themoviedb.org/3/<path> with retries.

    The TMDB edge is flaky from some networks (intermittent TLS handshake
    drops at a high failure rate; failed handshakes end instantly), so we retry
    before giving up: with ~75% per-attempt handshake failure, 12 attempts give
    high confidence while adding little latency. Returns {} on persistent
    failure, and does not raise.

    The 12 attempts only buy anything while failures are FAST: a hung TMDB
    would otherwise cost 12 x 12s on every call, and callers chain several
    calls per movie step (search -> discover -> per-movie runtime/details ->
    watch providers). One wall-clock budget caps the whole call; each attempt
    is offered min(TIMEOUT, whatever budget is left).
    """
    deadline = time.monotonic() + TMDB_BUDGET_S
    for _ in range(attempts):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            log.warning(
                "TMDB budget exhausted after %.1fs (%s); giving up",
                TMDB_BUDGET_S, path,
            )
            break
        try:
            with httpx.Client(timeout=min(TIMEOUT, remaining), headers=HEADERS) as client:
                r = client.get(
                    f"https://api.themoviedb.org/3/{path.lstrip('/')}",
                    params={"api_key": settings.tmdb_api_key, **params},
                )
                if r.status_code == 200:
                    return r.json()
                if r.status_code in {403, 401}:
                    break
        except Exception:
            continue
    return {}


def tmdb_watch_providers(tmdb_id: int, region: str = "IN") -> dict:
    """Get streaming/watch providers for a movie (region-aware). Returns flatrate (subscription),
    rent, and buy options — mimicking the TMDB MCP server's watch provider tool."""
    if not settings.tmdb_api_key:
        return {}
    key = f"tmdb-watch:{tmdb_id}:{region}"
    cached = ttl_cache.get(key)
    if cached:
        return cached
    data = _tmdb_json(f"movie/{tmdb_id}/watch/providers", {})
    region_data = (data.get("results") or {}).get(region, {})
    def _providers(entries: list) -> list[dict]:
        return [
            {"name": p.get("provider_name"), "logo": f"https://image.tmdb.org/t/p/w92{p['logo_path']}" if p.get("logo_path") else None}
            for p in (entries or [])
        ]
    result = {
        "tmdb_id": tmdb_id,
        "region": region,
        "link": region_data.get("link"),
        "flatrate": _providers(region_data.get("flatrate")),
        "rent": _providers(region_data.get("rent")),
        "buy": _providers(region_data.get("buy")),
        "source": "tmdb-watch-providers",
    }
    if region_data:
        ttl_cache.set(key, result, ttl_seconds=12 * 3600)
    return result


def tmdb_trending(media_type: str = "movie", time_window: str = "week", limit: int = 8) -> list[dict]:
    """Get trending movies or TV shows — great for 'what to watch at home' suggestions."""
    if not settings.tmdb_api_key:
        return []
    key = f"tmdb-trending:{media_type}:{time_window}"
    cached = ttl_cache.get(key)
    if cached:
        return cached
    data = _tmdb_json(f"trending/{media_type}/{time_window}", {})
    items = []
    for row in (data.get("results") or [])[:limit]:
        title = row.get("title") or row.get("name")
        items.append({
            "id": f"tmdb-trending:{row.get('id')}",
            "tmdb_id": row.get("id"),
            "title": title,
            "kind": "movie" if media_type == "movie" else "tv",
            "text": row.get("overview") or "",
            "source": "tmdb-trending",
            "estimated_cost": 0,
            "duration_min": 120,
            "intensity": "low",
            "vote": row.get("vote_average"),
            "poster_url": f"https://image.tmdb.org/t/p/w342{row['poster_path']}" if row.get("poster_path") else None,
            "watch_at_home": True,
            "subtype": "streaming",
        })
    ttl_cache.set(key, items, ttl_seconds=6 * 3600)
    return items


def tmdb_recommendations(tmdb_id: int, limit: int = 6) -> list[dict]:
    """Get movie recommendations based on a movie — 'more like this'."""
    if not settings.tmdb_api_key:
        return []
    key = f"tmdb-rec:{tmdb_id}"
    cached = ttl_cache.get(key)
    if cached:
        return cached
    data = _tmdb_json(f"movie/{tmdb_id}/recommendations", {})
    items = []
    for row in (data.get("results") or [])[:limit]:
        items.append({
            "id": f"tmdb-rec:{row.get('id')}",
            "tmdb_id": row.get("id"),
            "title": row.get("title"),
            "kind": "movie",
            "text": row.get("overview") or "",
            "source": "tmdb-recommendation",
            "estimated_cost": 0,
            "duration_min": 130,
            "intensity": "low",
            "vote": row.get("vote_average"),
            "poster_url": f"https://image.tmdb.org/t/p/w342{row['poster_path']}" if row.get("poster_path") else None,
            "watch_at_home": True,
            "subtype": "streaming",
        })
    ttl_cache.set(key, items, ttl_seconds=12 * 3600)
    return items


def web_snippets(query: str, limit: int = 4) -> list[dict]:
    key = f"web:{query}"
    cached = ttl_cache.get(key)
    if cached:
        return cached
    try:
        from ddgs import DDGS

        results = []
        with DDGS() as ddgs:
            for row in ddgs.text(query, max_results=limit):
                results.append(
                    {
                        "id": f"web:{row.get('href')}",
                        "title": row.get("title"),
                        "kind": "web",
                        "text": row.get("body") or "",
                        "url": row.get("href"),
                        "source": "duckduckgo",
                    }
                )
        ttl_cache.set(key, results, ttl_seconds=2 * 3600)
        return results
    except Exception:
        return []

