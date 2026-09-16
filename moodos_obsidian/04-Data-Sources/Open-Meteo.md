---
tags: [moodos, data-source, provider]
---

# Open-Meteo

Weather provider. Free, **no API key**.

## Source

`providers.get_weather` (`providers.py:19`):
`https://api.open-meteo.com/v1/forecast` with `latitude`, `longitude`,
`current_weather`, `forecast_days=1`. Returns temperature °C, condition label
(via `_weather_label`, `providers.py:61`), weather code, and a `rainy` bool
(from `precipitation`/`weather_code`).

Wrapped + cached by [[Get Weather]]. Internet outage → `{}` (empty/generic
weather), so plans still build with `rainy=false`.

## Consumed by

- [[Hard Filtering and Constraints]] — outdoor stops (`needs_clear_weather`)
  are gated when raining (`ranking.py:69`).
- [[Plan Assembly]] — `_heuristic_plan` rainy logic (`orchestrator.py:468-493`).
- [[Ranking and Scoring]] — indoor context bonus when rainy.
- [[Direct Chat]] — weather replies.
- The LLM plan prompt (`orchestrator.py:1369-1375`).

## Connects to

- [[Get Weather]] · [[TTL Cache]]
- [[Direct Chat]]

## Used by

- [[Request Flow]] · [[Architecture-Overview]]