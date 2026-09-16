---
tags: [moodos, core-logic, nlu, language]
---

# Music Language Resolution

Making the playlist feel local: if the user didn't name a music language, the
app infers one from where they are.

## Sources (`nlu.py`)

- `MUSIC_LANGUAGE_TERMS` (`nlu.py:50`) — canonical map for every Indian
  language alias (hindi/bollywood/desi, gujarati/gujrati, punjabi/panjabi,
  tamil/tamizh, telugu, kannada/kanada, marathi, bengali/bangla, malayalam,
  urdu, odia...).
- `detect_music_language(message)` (`nlu.py:114`) — returns a language only when
  a music-ish context word is present (`MUSIC_TERMS`, `nlu.py:68`: songs,
  playlist, gaana, bhajan, etc.), so "I like Hindi films" can't hijack a
  playlist but "Punjabi songs" can.
- `infer_locale_language(city, state)` (`nlu.py:129`) — state map first
  (`STATE_LANGUAGE`, `nlu.py:77`), then city map (`CITY_LANGUAGE`, `nlu.py:96`).

## Pipeline usage (`orchestrator.py:1244-1252`)

Explicit slot wins; otherwise infer from the reverse-geocoded location, then
set `music_language` and `music_region` (country code, default `IN`). The
language is passed into:

- `_derive_search_query` music queries (`nlu.py` term used inside
  [[Derive Search Query]]);
- playlist/`why` blurbs (`_music_why`, `orchestrator.py:793`);
- music filler titles (`_best_filler`, `orchestrator.py:840-843`);
- iTunes/Spotify search country ([[Search Music]]).

## Connects to

- [[Intent and Mood Extraction]] · [[Derive Search Query]] · [[Search Music]]

## Used by

- [[Request Flow]]