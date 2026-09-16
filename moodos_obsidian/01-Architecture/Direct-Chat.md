---
tags: [moodos, architecture, chat]
---

# Direct Chat

Short answers ("where am I?", "what's the weather?", "what do you know about
me?", "help") bypass the plan pipeline entirely.

Source: `moodos/chat.py`.

## Behavior

- `classify_turn` (`nlu.py:145`) decides the topic: `location`, `weather`,
  `memory`, `help`, or `other`.
- `answer_chat(message, user_id, lat, lon)` (`chat.py:80`) builds live facts
  once (`live_facts`, `chat.py:23`): reverse geo place, weather, and the top-6
  Mem0 memories.
- Topic-specific replies:
  - `_location_reply` (`chat.py:40`) — "You are near X (lat, lon)" + default-city
    warning when no GPS.
  - `_weather_reply` (`chat.py:55`) — temperature/condition, indoor-first note
    when raining.
  - `_memory_reply` (`chat.py:66`) — memories joined, or "nothing stored yet".
  - `_help_reply` (`chat.py:73`).
  - default → `router.extract_json(CHAT_PROMPT ...)` (`chat.py:92`), falls back
    to help reply when the LLM returns nothing.
- Response shape: `{mode: "chat", topic, reply, location, weather,
  used_default_location, plan: null}` — `app.js` renders the `reply` text
  directly.

This is the path used when `handle_message` sees `mode == "chat"`
(`orchestrator.py:246`).

## Connects to

- [[Mem0]] · [[Open-Meteo]] · [[OpenStreetMap]]
- [[Agent Router]] (for the fallback LLM reply)
- [[Route Plan]]

## Used by

- [[Request Flow]]