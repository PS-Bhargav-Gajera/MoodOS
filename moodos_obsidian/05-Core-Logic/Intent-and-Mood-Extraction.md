---
tags: [moodos, core-logic, nlu, extraction]
---

# Intent and Mood Extraction

Turning the free-text prompt into structured slots (`moodos/nlu.py`).

## Path

1. `classify_turn` (`nlu.py:145`) first decides **chat vs plan** using hint
   lists (`PLAN_HINTS`, `HOME_HINTS`, `LOCATION_HINTS`, `WEATHER_HINTS`,
   `MEMORY_HINTS`, `HELP_HINTS`) plus ₹/hour regexes. A trailing `?` that
   matches nothing → `other` chat.
2. `extract_intent(message)` (`nlu.py:269`):
   - `heuristic_extract` (`nlu.py:193`) — deterministic: budget regex
     (`₹\s*NN`, `N rupees/rs`), hours regex (+ `four hours` override),
     **`party_size`** (`nlu.py:214-221`): `N friends/people/ppl/persons/of us`
     or `family/group/party of N`, accepted only in the range **2–50**
     (`1 < n <= 50`; solo → `None`), social via `alone/solo/by myself`,
     intensity via `nothing intense/exhausted/tired/calm`,
     `current/desired` moods, `rainy`, `stay_home`, `food_priority` (food word
     + emphasis word, `nlu.py:229-236`), `want_movie` (`nlu.py:237-244`),
     `music_language` via [[Music Language Resolution]].
   - LLM `EXTRACT_PROMPT` (`nlu.py:164`, which also documents `party_size`)
     via [[Agent Router]] `extract_json`, with a defensive merge: LLM
     non-empty values override the heuristic base (`nlu.py:275`), **except**
     the numeric slots `duration_hours`, `budget_inr`, `party_size`
     (`_heuristic_numeric`, `nlu.py:274-278`) — the explicit regex count is
     authoritative when both find one. Tags `_agent`/`_model`.

## Slots produced

`intent`, `current_mood`, `desired_mood`, `mood_intensity`, `mood_trajectory`,
`budget_inr`, `duration_hours`, `party_size`, `social`, `intensity`, `city`,
`implicit_preferences`, `constraints`, `stay_home`, `food_priority`,
`want_movie`, `music_language`.

**`budget_inr` is the GROUP total** whenever `party_size > 1` ("Rs5000 for 5
friends"): cost checks scale each candidate's per-person `estimated_cost` by
`ranking.party_size(slots)` (`ranking.py:27`) — see [[Hard Filtering and
Constraints]] / [[Budget Fit Duration]].

## Consumers

- `run_pipeline` (`orchestrator.py:2049`) — mood/prefs projection
  (`:2085-2100`), stay-home flag (`:2136`), music region inference (`:2152`).
- [[Ranking and Scoring]] / [[Hard Filtering and Constraints]].
- [[Plan Assembly]].

## Connects to

- [[Agent Router]] · [[Music Language Resolution]]
- [[Analyze Mood]] · [[Extract Preferences]] (tool views)

## Used by

- [[Request Flow]] · [[Route Plan]]