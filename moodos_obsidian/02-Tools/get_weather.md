---
tags: [moodos, tool, mcp]
---

# Get Weather

MCP tool `get_weather` → `lambda lat, lon: providers.get_weather(lat, lon)`
(`moodos/mcp_server.py:27`).

## Signature

`get_weather(lat: float, lon: float) -> dict`
Returns temperature (`°C`), condition label, `rainy` bool, and weather code details.

## Behavior

`providers.get_weather` (`providers.py:19`) calls the **Open-Meteo** forecast
API (no key). It is cached for a few minutes ([[TTL Cache]]).

Weather feeds:
- `hard_filter` — drops outdoor/clear-weather-required places when raining
  ([[Hard Filtering and Constraints]]).
- `_heuristic_plan` — the rainy indoor-pause step and no-walk logic
  (`orchestrator.py:468-493`).
- Scoring context bonus for indoor items when rainy ([[Ranking and Scoring]]).

Called 2-3× per plan (direct + inside the parallel tasks, `orchestrator.py:1238,
1281`) — cache makes the duplicates cheap.

## Connects to

- [[Open-Meteo]] · [[TTL Cache]]
- [[Hard Filtering and Constraints]] · [[Ranking and Scoring]]

## Used by

- `run_pipeline` (`orchestrator.py:1238, 1281`)
- [[Direct Chat]] (`chat.py:28`)
- Public MCP surface