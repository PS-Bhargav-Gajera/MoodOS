---
tags: [moodos, tool, mcp]
---

# Get Weather

MCP tool `get_weather` → `lambda lat, lon: providers.get_weather(lat, lon)`
(`moodos/mcp_server.py:29`).

## Signature

`get_weather(lat: float, lon: float) -> dict`
Returns `temperature_c`, `precipitation`, `weather_code`, `condition` label,
`rainy` bool, `lat`, `lon`, `source` (`open-meteo`), `freshness` (`live`).

## Behavior

`providers.get_weather` (`providers.py:20`) calls the **Open-Meteo** forecast
API (no key) for `temperature_2m`, `weather_code`, `precipitation`,
`wind_speed_10m`. Result is TTL-cached 15 min ([[TTL Cache]],
`providers.py:55`); a broken cache log-and-falls through to a live fetch
(`providers.py:23-29`).

When the API is down it returns an explicit unavailable dict instead of
raising: `temperature_c: null`, `rainy: false`, `condition: "unknown"`,
`source: "unavailable"`, `freshness: "unknown"` (`providers.py:58-66`).

Weather feeds:
- `hard_filter` — drops outdoor/clear-weather-required places when raining
  ([[Hard Filtering and Constraints]], `ranking.py:110`).
- `_heuristic_plan` — the rainy indoor-pause step / no-walk logic
  (`orchestrator.py:673, 738-750`).
- Scoring context bonus for indoor items when rainy ([[Ranking and
  Scoring]], `ranking.py:152-153`).

Called **once** per plan (`orchestrator.py:2132`) — before the parallel
lookup batch, because it gates the music seed rotation.

## Connects to

- [[Open-Meteo]] · [[TTL Cache]]
- [[Hard Filtering and Constraints]] · [[Ranking and Scoring]]

## Used by

- `run_pipeline` (`orchestrator.py:2132`)
- [[Direct Chat]] (`chat.py:33`)
- Public MCP surface
