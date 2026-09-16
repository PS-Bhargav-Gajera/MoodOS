---
tags: [moodos, data-source, provider]
---

# OpenStreetMap

Free geospatial data: **Nominatim** (forward/reverse geocoding) + **Overpass API**
(POI queries) + **ip-api.com** (IP → city-level coords). No key.

## Endpoints used

| Purpose | Function | Endpoint |
|---|---|---|
| Forward geocode text | `location.geocode_text` (`location.py:22`) | `nominatim.openstreetmap.org/search` |
| Reverse geocode coords | `providers.reverse_geocode` (`providers.py:75`) | Nominatim `reverse` |
| Nearby POIs (cafes/restaurants/parks) | `_overpass_nearby` (`providers.py:503`) | `overpass-api.de/api/interpreter` |
| Walk fallback search | `_nominatim_nearby` (`providers.py:574`) | Nominatim search with `viewbox` |
| Nearby cinemas | `providers.nearby_cinemas` (`providers.py:157`) | Overpass `amenity=cinema` |
| IP location | `location.ip_location` (`location.py:63`) | `ip-api.com/json/{ip}` |

## Derived enrichment

- **Food costing**: OSM rarely has prices → `_estimate_food_cost`
  (`providers.py:250`) derives a tier + ₹ from tags (`stars`, `price:range`,
  name keywords). Always tagged `price_is_estimate`.
- **Institutional filter**: `_institutional_flag` (`providers.py:231`) drops
  campus/staff-only canteens and `access=private` venues.
- **Opening hours**: `_opening_hours_is_open` (`providers.py:288`) parses common
  `24/7` and `We HH:MM-HH:MM` forms; unparseable → "unknown", `likely_closed`.
- **Distance gating**: candidates > 8 km (places/food) or > 20 km (movie
  venues) are filtered ([[Hard Filtering and Constraints]], `ranking.py:71-76`).

## Connects to

- [[Find Nearby Places]] · [[Search Restaurants]] · [[Search Restaurants By Mood]] · [[Find Nearby Cinemas]]
- [[Location Resolution]]
- [[TTL Cache]] (20m/location, 24h/cinemas)

## Used by

- [[Request Flow]] · [[Architecture-Overview]]