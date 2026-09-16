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
2. `extract_intent(message)` (`nlu.py:254`):
   - `heuristic_extract` (`nlu.py:191`) — deterministic: budget regex
     (`₹\s*NN`, `N rupees/rs`), hours regex (+ `four hours` override),
     social via `alone/solo/by myself`, intensity via `nothing intense/
     exhausted/tired/calm`, `current/desired` moods, `rainy`,
     `stay_home`, `food_priority` (food word + emphasis word, `nlu.py:215-222`),
     `want_movie` (`nlu.py:223`), `music_language` via
     [[Music Language Resolution]].
   - LLM `EXTRACT_PROMPT` (`nlu.py:164`) via [[Agent Router]] `extract_json`,
     with a defensive merge: LLM non-empty values override the heuristic
     base (`nlu.py:259`). Tags `_agent`/`_model`.

## Slots produced

`intent`, `current_mood`, `desired_mood`, `mood_intensity`, `mood_trajectory`,
`budget_inr`, `duration_hours`, `social`, `intensity`, `city`,
`implicit_preferences`, `constraints`, `stay_home`, `food_priority`,
`want_movie`, `music_language`.

## Consumers

- `run_pipeline` (`orchestrator.py:1200`) — mood/prefs projection
  (`:1206-1220`), stay-home flag, music region inference.
- [[Ranking and Scoring]] / [[Hard Filtering and Constraints]].
- [[Plan Assembly]].

## Connects to

- [[Agent Router]] · [[Music Language Resolution]]
- [[Analyze Mood]] · [[Extract Preferences]] (tool views)

## Used by

- [[Request Flow]] · [[Route Plan]]