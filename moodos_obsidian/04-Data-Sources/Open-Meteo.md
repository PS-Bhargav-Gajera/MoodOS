---
tags: [moodos, data-source, provider]
---

# Open-Meteo

Weather provider. Free, **no API key**.

## Source

`providers.get_weather` (`providers.py:20`):
`https://api.open-meteo.com/v1/forecast` with `latitude`, `longitude` and
`current=temperature_2m,weather_code,precipitation,wind_speed_10m`. Returns
temperature °C, condition label (via `_weather_label`, `providers.py:69`),
weather code, and a `rainy` bool (rain code set or `precipitation > 0`).
Cached 15 min (`providers.py:55`).

Wrapped + cached by [[Get Weather]]. Internet outage → a generic result
(`condition: "unknown"`, `rainy: false`, `source: "unavailable"`,
`providers.py:57-66`), so plans still build with `rainy=false`.

## Consumed by

- [[Hard Filtering and Constraints]] — outdoor stops (`needs_clear_weather`)
  are gated when raining (`hard_filter`, `ranking.py:110`).
- [[Plan Assembly]] — `_heuristic_plan` rainy logic (`orchestrator.py:673`,
  `725-743`).
- [[Ranking and Scoring]] — indoor context bonus when rainy.
- [[Direct Chat]] — weather replies.
- The LLM plan prompt (`PLAN_PROMPT`, `orchestrator.py:416`, formatted with
  `weather=` at `orchestrator.py:2298-2304`).

## Connects to

- [[Get Weather]] · [[TTL Cache]]
- [[Direct Chat]]

## Used by

- [[Request Flow]] · [[Architecture-Overview]]