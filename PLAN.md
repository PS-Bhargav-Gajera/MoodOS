# PLAN.md — MoodOS

> MoodOS is a **plan generator, not a chatbot**. Input: mood + context. Output: a structured, sensible evening plan.
> Stack: Python/FastAPI · vanilla JS/HTML/CSS · SQLite · Windows/PowerShell
> **Project type: learning project, not production.** "Done" means: it works end to end, I can explain every decision, and the gaps I did not fix are written down honestly in Section 7 (future work).
> Rule: a task is done only when its **Done when** line is true and verified. Update this file after every work session.

---

## 1. Definition of Done (revised for a learning project)

- [ ] **D1 Core promise:** given mood + context, it returns a structured evening plan (timeline + meta-grid) with no crash.
- [ ] **D2 Plan quality:** checked on 10 real inputs (Section 4); failures are grouped and explained.
- [ ] **D3 Integrations:** each integration has a known failure behavior. Verified ones are ticked in Section 2; the rest are listed in Section 7.
- [ ] **D4 Frontend:** timeline and meta-grid shipped. Mood-arc: **decision = ______ (minimal version / future work)**
- [ ] **D5 Understanding:** LESSONS.md has 5-8 lessons, each with a real example from this project.
- [ ] **D6 Handover:** README (setup, env keys, how to run) and FUTURE.md exist.

> Dropped from the original plan (moved to Section 7): full PDF analysis, contract tests for every integration, fresh-user test.

---

## 2. Integration Contracts

| Integration | Input | Must return | On failure (fallback) | Status |
|---|---|---|---|---|
| Open-Meteo | lat, lon | temperature, rain chance | neutral weather (rainy: None) + indoor option | [x] Verified: timeout, bad body, no caching of bad data |
| OSM/Overpass | lat, lon, category | nearby places | honest empty list / 503, no crash | [ ] Wrapper has tests; second client unguarded (Section 7) |
| TMDB | mood or genre | a few movie options | skip the movie slot | [~] 6 s budget per call, 12 fast retries kept. Chain budget deferred |
| Spotify | mood | track suggestion | skip the music slot | [ ] Has failure-path tests; not re-audited |
| Mem0 | user id | stored preferences | run without personalization | [ ] Not tested for failure |
| Groq | structured prompt | valid structured output | fall back to Gemini, then heuristic | [~] Extraction path budgeted at 8 s; no contract test |
| Gemini | structured prompt | valid structured output | next model, then heuristic | [~] Same as Groq |

> No MCP is in use. These are plain APIs called by Python code in a fixed order.

---

## 3. Work Phases (trimmed)

### Phase 2 — Integration hardening (mostly done)
- [x] Open-Meteo: own timeout, neutral fallback, bad-body fix (tests first)
- [x] Intent extraction: 8 s total budget, heuristic fallback
- [x] TMDB: 6 s budget per call
- [ ] Commit each finished task separately (git)

### Phase 3 — End-to-end run (replaces full PDF analysis)
- [ ] Run 10 real inputs, fill Section 4
- [ ] Group failures by type, pick the top one, explain it
- **Done when:** the table is filled and each failure has a one-line explanation.

### Phase 4 — Optional: minimal mood-arc
- [ ] Draw the arc from existing mood slots; milestones from real plan steps
- **Done when:** the arc renders from real plan data. Skip it if time is short, and say so in the README.

### Phase 5 — Documents
- [ ] README
- [ ] LESSONS.md
- [ ] FUTURE.md (copy Section 7)

---

## 4. End-to-End Run (10 cases)

**Run 1 (stale build)** — executed 2026-10-16 17:26-17:38 against the server then running: PID 14036, started **14-10-2026 15:42:14**, older than the newest file in `moodos/` (**providers.py, 16-10-2026 16:39:19**), uvicorn started without `--reload`.

| # | Input (mood + context) | Plan sensible? | Time taken | Failure type | Explanation |
|---|---|---|---|---|---|
| 1 | exhausted after college, alone, Rs1000, four hours, "nothing intense" (exhausted -> relaxed, solo) | No | 82.03s | empty slot (no venue) | walk 20m -> The Lunchbox 104m -> Paddington 95m -> Calm hindi music 13m; 240/240m, Rs450. Two films back-to-back with no meal, both with showtimes=[] and no cinema venue (OSM breaker open). Live weather: cloudy, rainy=False, 26.8C. |
| 2 | great mood, buzzing with energy, 3 friends, Ahmedabad, Rs1500 each, about 3 hours (great -> fun, high) | No | 69.74s | bad format | walk 7m -> The Odyssey 173m; 184/180m, Rs660. budget_notes claims the walk step was "Removed" while that same walk is still order 1; walk title says "20-minute" but duration is 7m; one long film only, no venue/showtime. |
| 3 | anxious and wound up, quiet calm evening with partner, Rs2000, 2 hours (anxious -> calm, date) | No | 65.94s | empty slot (no venue) | walk 20m -> Runner 97m; 121/120m, Rs440 (22% of budget). No cinema/showtime for the film and no dinner element for a date; places and restaurants unavailable (OSM breaker open). |
| 4 | pouring rain and drenched, cozy indoor evening, Rs2500, 3 hours (uncomfortable -> cozy, solo) | Yes | 53.06s | weather mismatch (message vs API) | Matchbox the Movie 127m -> Calm hindi music 30m -> rest 23m; 180/180m, Rs0, stay_home=True. The message says pouring rain but the live API returned cloudy, rainy=False, 26.8C - the indoor plan matched the request anyway, so nothing visible broke. |
| 5 | clear skies, long evening walk and street food with sister, Rs800, 4 hours (positive -> relaxed, family) | No | 57.51s | over budget | walk 20m -> street food 60m Rs600 -> Spider-Man: Brand New Day 145m Rs440; 233/240m but Rs1040 vs Rs800 (over_budget=True, excess Rs240). "Long walk" became 20m, an unrequested 145m film was added, and the live sky was cloudy rather than clear. |
| 6 | only 1 hour before the bus, quick coffee and snack stop, Rs200 (neutral -> entertained, solo) | No | 60.31s | empty slot (requested stop missing) | walk 20m -> Calm hindi music 30m -> rest 10m; 60/60m, Rs0. slots.food_priority=True but no coffee or food step at all - restaurant lookup failed (OSM breaker open), 10 of the 60 minutes is bare rest. |
| 7 | free the whole night, 7 hour outing, me and 4 friends, Rs5000 (neutral -> entertained, medium) | No | 56.91s | empty slot | walk 20m -> Calm hindi music 30m -> "Remaining free time" 370m; 420/420m, Rs0 of Rs5000. 370 of 420 minutes (88%) is one unfilled rest block; no places, restaurants or cinemas came back. |
| 8 | bored, want to do something fun tonight; no budget, no city, no duration (bored -> fun, medium) | No | 57.81s | mood mismatch | walk 20m -> rest 80m -> Insidious: Out of the Further 106m -> Calm hindi music 30m; 240/240m (4h default), Rs220. A horror film for a "fun" ask whose blurb claims "low-intensity ... from a calm state"; 80m free-time hole mid-plan; no venue/showtime. City came from the IP resolver (Delhi). |
| 9 | completely exhausted but take me to the loudest, most intense high-energy dance night; 6 hours, Rs3000 (contradiction: tired + high-energy) | No | 79.05s | mood mismatch + bad format | walk 90m -> Whiplash 107m -> "Late-night club (seed negative)" 90m Rs1500 -> Calm hindi wind-down music 30m -> rest 35m; 360/360m, Rs1750. The night ends calm after the dance club, seed text "(seed negative)" leaks into a step title, and the walk is titled "20-minute" but lasts 90m. |
| 10 | | | | | |

**Run notes (observed 2026-10-16, live server at 127.0.0.1:8000):**
- All 9 calls returned HTTP 200 with a plan - no crashes, no error responses. Times: 82.03, 69.74, 65.94, 53.06, 57.51, 60.31, 56.91, 57.81, 79.05 s (mean about 64.7 s per plan).
- Weather was identical for all 9 (open-meteo, freshness=live, 15-min TTL): cloudy, rainy=False, 26.8 C. A rainy reading never appeared, so the "rainy day" case (row 4) exercised only the user's claim and the "clear day" case (row 5) ran against a cloudy reading - real-rain behaviour is still untested (row 10 is yours to run offline).
- Every call returned the same 5 provider_errors: books and music both failed with `got an unexpected keyword argument 'q'`, plus Overpass unavailable for places, restaurants and cinemas (breaker OPEN: "skipping OSM for 120.0s"). The current code passes `query=`, so the running server is a pre-fix build (process started 14-10-2026 15:42, uvicorn without --reload) - the q= failures are old code, not today's changes.
- Location resolved via IP to Delhi, Delhi (28.6519, 77.2314) on all 9 requests although no message named a city; no step carried a real venue, and every computed inter-step distance was 0.0 km.
- The response has no start/end clock times, so time-of-day overlap could not be checked from the API; duration fit was checked instead - budget_fit.within_tolerance was True for rows 1-9. Closed-place checking was impossible: no venue or opening-hours data came back at all.
- Server log grep over run.out.log, run.err.log, server.out.log, server.err.log, smoke_8011.out.log, smoke_8011.err.log and server_restart.log: **"budget exceeded" = 0 lines, "LLM returned nothing" = 0 lines**. Both messages were introduced today, after the running server loaded its modules, so 0 is expected until a restart.

**Run 2 (current build)** — executed 2026-10-16 19:05-19:16 against PID **20704**, started **19:03:38** (newer than providers.py 16:39:19). Merged restart note: Run 1 hit the pre-fix build (PID 14036); a `--reload` restart at 18:53 died within minutes; the user's next window left no listener either (`/api/health` refused, 0 rows on port 8000), so after a second failed verification I started the current-build server myself (no `--reload`, append-redirected into run_new.log) and ran the table below.

| # | Input (mood + context) | Plan sensible? | Time taken | Failure type | Explanation |
|---|---|---|---|---|---|
| 1 | exhausted after college, alone, Rs1000, four hours, "nothing intense" (exhausted -> relaxed, solo) | No | 101.01s | mood mismatch | walk 20m -> walk 4m -> Mind Relaxing Lofi 31m -> Remaining free time 91m -> Resident Evil 95m; 241/240m, Rs220. A horror film for a "nothing intense" calm ask; the free-time block sits in the middle of the plan and the film is the last stop. |
| 2 | great mood, buzzing with energy, 3 friends, Ahmedabad, Rs1500 each, about 3 hours (great -> fun, high) | No | 76.45s | planner budget fallback + no venue | walk 20m -> Har Funn Maula 31m -> Remaining free time 130m; 181/180m, Rs0 of Rs1500. agents.plan=heuristic-planner: Gemini hit the 35 s budget ("LLM plan exceeded budget; using heuristic plan" in run_new.log) and the heuristic only adds walk/music/rest. No night-out venue (Overpass 502). City resolved to Delhi via IP - "Ahmedabad" is message text only; the request carries no city field and app.py:178 takes typed city from user_label/city, never from the message. |
| 3 | anxious and wound up, quiet calm evening with partner, Rs2000, 2 hours (anxious -> calm, date) | No | 73.81s | empty slot (no venue) | Ve Kamleya LoFi 18m -> Fall 2: Deadpoint 98m; 116/120m, Rs440. No dinner element for a date (restaurants down); the music step's why_text says "after the film" although it plays before it. |
| 4 | pouring rain and drenched, cozy indoor evening, Rs2500, 3 hours (uncomfortable -> cozy, solo) | Yes | 65.37s | weather mismatch (message vs API) + duplicate step | Cozy Evening Lo-fi 16m -> Animals streaming 106m -> Cozy Evening Lo-fi 16m (same track twice) -> rest 42m; 180/180m, Rs0, stay_home=True. Live weather was clear, rainy=False; the indoor plan matched the request anyway. |
| 5 | clear skies, long evening walk and street food with sister, Rs800, 4 hours (positive -> relaxed, family) | No | 40.86s | empty slot (requested stop missing) | walk 20m -> Mind Relaxing Lofi 31m -> Remaining free time 190m; 241/240m, Rs0 of Rs800. "Long walk" stayed 20m, street food never planned (restaurants down), 190 of 240 minutes is one free-time block. |
| 6 | only 1 hour before the bus, quick coffee and snack stop, Rs200 (neutral -> entertained, solo) | No | 37.52s | time overflow + empty slot | walk 20m -> three 30m music steps; 110m planned for a 60m window, yet budget_fit still reports within_tolerance=True (delta 50 > tolerance 2 - contradictory field). No coffee/snack step (restaurants down). |
| 7 | free the whole night, 7 hour outing, me and 4 friends, Rs5000 (neutral -> entertained, medium) | No | 57.21s | empty slot + dead time | walk 20m -> travel 4m -> 2 short music -> Comfort meal 90m Rs3200 -> Remaining free time 246m -> pause 45m -> wander 3m; 420/420m. 294 of 420 minutes (70%) is rest/free-time filler; music why_texts call the tracks "calming" on a night out. |
| 8 | bored, want to do something fun tonight; no budget, no city, no duration (bored -> fun, medium) | No | 37.27s | mood mismatch | walk 20m -> Har Funn Maula 30m -> Rock On!! 11m -> Remaining free time 160m -> pause 19m; 240/240m, Rs0. Calm lofi for a "fun" ask whose why_text says it moves bored -> calm; no fun venue (Overpass down). |
| 9 | completely exhausted but take me to the loudest, most intense high-energy dance night; 6 hours, Rs3000 (contradiction: tired + high-energy) | No | 65.62s | mood mismatch + bad format | five dance/Kendrick Lamar music steps, each justified as "Calming background music" -> "Late-night club (seed negative)" 90m Rs1500 -> Remaining free time 120m; 382/360m, Rs1500. "(seed negative)" still leaks into a step title, unchanged from Run 1. |
| 10 | | | | | |

**Run 2 notes (observed 2026-10-16, live server at 127.0.0.1:8000):**
- All 9 calls returned HTTP 200 (access log: 9 x `POST /api/plan ... 200 OK`). Times: 101.01, 76.45, 73.81, 65.37, 40.86, 37.52, 57.21, 37.27, 65.62 s; mean 61.7 s, median 65.37 s (Run 1 mean: 64.7 s).
- provider_errors: only Overpass entries now - places/restaurants/cinemas in 8 calls, places+restaurants in row 4 (stay_home, no cinema lookup). The two Run-1 `search_books()/search_music() got an unexpected keyword argument 'q'` errors are gone, confirming the stale-build artifact is fixed on the current build.
- Overpass genuinely failed with HTTP 502 from overpass-api.de (`overpass nearby search failed: Server error '502 Bad Gateway'`), logged twice as `overpass budget of 12.0s exhausted`. The new TMDB deadline fired live once: `TMDB budget exhausted after 6.0s (movie/400136); giving up`.
- Weather identical for all 9 again (open-meteo live, 15-min TTL): clear, rainy=False, 25.2 C - still no rainy reading, so real-rain behaviour remains untested (row 10 is yours to run offline).
- Location resolved via IP to Delhi, Delhi on all 9 requests (runner sends no lat/lon and no city field). Row 2's "Ahmedabad" exists only in the message text; app.py:178 takes typed city from `user_label`/`city` only, so the resolver never saw it.
- Log grep on run_new.log: **"budget exceeded" = 0 lines, "LLM returned nothing" = 0 lines**, verified by byte-level scan of the raw file (the file mixes a UTF-16 head from the failed 18:53 --reload attempt with the ANSI tail of the current server, so line-oriented tools that decode it as one encoding under-report; the tail also holds 9 access-log lines and no Traceback). Adjacent budget messages that did fire: `LLM plan exceeded budget; using heuristic plan` x1 (row 2), `TMDB budget exhausted after 6.0s` x1, `overpass budget of 12.0s exhausted` x2.

**Cases to cover:** different moods · a rainy and a clear day · short and long time window · missing context · one run with the network off.
**Target pass rate:** ____ % (decide before running, so the goal does not move)

---

## 5. Decisions

| Decision | My choice | Reason |
|---|---|---|
| Extraction budget 8 s: wait for better mood slots, or plan fast? | ______ | |
| Mood-arc: minimal version or future work? | ______ | |

---

## 6. Session Log

| Date | Done | Next |
|---|---|---|
| 2026-10-16 | Audit run. Open-Meteo contract + bad-body fix. Extraction budget 8 s. TMDB budget 6 s. 324 tests passing | End-to-end run (10 cases) |
| 2026-10-16 | End-to-end run against live /api/plan: 9 of 10 cases executed and filled in Section 4 (mean 64.7 s per plan, all HTTP 200). Log grep: "budget exceeded" 0, "LLM returned nothing" 0. Found the running server is a pre-fix build (started 14-10, no --reload), so music/books still fail with the q= kwarg | Case 10 offline; restart server on current build and re-run the table |
| 2026-10-16 | Run 2 of Section 4 on the current build (PID 20704, started 19:03:38): same 9 cases, mean 61.7 s, all HTTP 200. q= provider_errors gone; Overpass down with a real 502; TMDB 6 s deadline and Gemini 35 s planner budget each fired once (row 2 fell back to heuristic-planner). run_new.log grep: "budget exceeded" 0, "LLM returned nothing" 0 | Case 10 offline; fill Section 5 decisions |
| 2026-10-20 | Crisis guard (probe finding: distress message got a normal 200 plan): new `moodos/crisis.py` deterministic phrase check, shared helper called in `/api/plan` BEFORE resolve_location (no network, no 409) and at the top of `handle_message`; match returns the existing chat-shaped reply with Tele-MANAS 14416 / 1-800-891-4416 and 112, zero writes/logging; `tests/test_crisis.py` 21 tests (fail-first shown), full suite 347 passed | Restart server on the new build; re-probe the distress sentence |
| | | |

---

## 7. Future Work (known gaps, not fixed on purpose)

| Gap | Impact | Idea for the fix |
|---|---|---|
| Mood-arc missing (backend field + frontend render) | Mood story invisible to the user | Build `mood_arc` from real plan steps; map `slots.current_mood` / `desired_mood` to the template |
| TMDB chain has no shared budget (`as_completed` has no timeout) | Plan can wait up to ~48 s if TMDB hangs | Put one timeout on the whole movie batch in the orchestrator |
| TMDB retries 429/404 in a tight loop; 401/403 silent | Rate-limit pile-up, hard to debug | Back off on 429, stop on 404, log bad key |
| `chat.py:107` has its own unbudgeted `extract_json` call | Chat can hang | Reuse the extraction budget |
| Second Overpass client bypasses breaker and budget | Places leg can stall | Route it through the `providers.py` wrapper |
| Abandoned LLM threads keep running after a timeout | Wasted API quota | Pass a deadline into the router so loops stop themselves |
| Mem0 `cloud_ready` decided once at startup | Silent loss of personalization | Re-check periodically |
| Failed Overpass walk query cached as "no walks" for 5 min | One failure hides results | Do not cache failures |
| No contract tests for Groq, Gemini, Mem0, TMDB | D3 not fully provable | One test per row: happy, odd input, timeout |
| Fresh-user test not done | Usability unknown | One person, no help, note where they get stuck |
