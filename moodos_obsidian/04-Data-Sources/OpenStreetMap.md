---
tags: [moodos, data-source, provider]
---

# OpenStreetMap

Free geospatial data: **Nominatim** (forward/reverse geocoding) + **Overpass API**
(POI queries) + **ipwho.is** (IP → city-level coords, HTTPS). No key.

## Endpoints used

| Purpose | Function | Endpoint |
|---|---|---|
| Forward geocode text | `location.geocode_text` (`location.py:26`) | `nominatim.openstreetmap.org/search` |
| Reverse geocode coords | `providers.reverse_geocode` (`providers.py:83`) | Nominatim `reverse` |
| Nearby POIs (cafes/restaurants/parks) | `_overpass_nearby` (`providers.py:693`) | `overpass-api.de/api/interpreter` |
| Walk fallback search | `_nominatim_nearby` (`providers.py:765`) | Nominatim search with `viewbox` |
| Nearby cinemas | `providers.nearby_cinemas` (`providers.py:365`) | Overpass `amenity=cinema` |
| IP location | `location.ip_location` (`location.py:66`) | `https://ipwho.is/{ip}` (or `https://ipwho.is/`) |

The IP leg is **not** OSM: it used to be `ip-api.com` over plain HTTP (client IP
in cleartext), so it moved to **ipwho.is** — free, HTTPS, no key, response
`success` checked (`location.py:66-89`). OSM tooling itself (Nominatim,
Overpass, OSRM) is unchanged.

## Derived enrichment

- **Food costing**: OSM rarely has prices → `_estimate_food_cost`
  (`providers.py:439`) derives a tier + ₹ from tags (`stars`, `price:range`,
  name keywords). Always tagged `price_is_estimate`.
- **Institutional filter**: `_institutional_flag` (`providers.py:420`) drops
  campus/staff-only canteens and `access=private` venues.
- **Opening hours**: `_opening_hours_is_open` (`providers.py:477`) parses common
  `24/7` and `We HH:MM-HH:MM` forms; unparseable → "unknown", `likely_closed`.
- **Distance gating**: candidates > 8 km (places/food) or > 20 km (movie
  venues) are filtered ([[Hard Filtering and Constraints]], `ranking.py:112-117`).

## Connects to

- [[Find Nearby Places]] · [[Search Restaurants]] · [[Search Restaurants By Mood]] · [[Find Nearby Cinemas]]
- [[Location Resolution]]
- [[TTL Cache]] (20m/places, 30m/cinemas+POIs, 6h/reverse-geocode)

## Used by

- [[Request Flow]] · [[Architecture-Overview]]