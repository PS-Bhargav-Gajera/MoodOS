# Diagram B — Worked example (end-to-end)

**User request**

> "I'm exhausted after college, alone, have ₹1000, four hours, and want to go out but nothing intense."

This diagram traces **actual intermediate values** through MoodOS. The LLM orchestrates tool calls; Mem0 / RAG / APIs remain the sources of facts.

---

## B0. Value snapshot (carried through the pipeline)

| Slot | Value | Source |
|---|---|---|
| Intent | Relaxation / solo outing | NLU |
| Current mood | Exhausted | Mood Engine |
| Desired mood | Relaxed + refreshed | Mood Engine |
| Mood intensity | Low | Mood Engine |
| Mood trajectory | Exhausted → Calm → Light entertainment → Refreshed | Mood Engine |
| Budget | Rs 1000 | Constraint extraction |
| Duration | 4 hours | Constraint extraction |
| Social | Solo | Context Engine |
| Intensity | Low | Context Engine + user text |
| Location | Current device location (e.g. Ahmedabad) | Context Engine |
| Weather | Live API + Redis TTL | Live APIs |
| Implicit prefs | Comfortable, nearby, low-effort | NLU + Mem0 |

---

## B1. Full trace

```mermaid
flowchart TB
  U["USER<br/>exhausted after college · alone · Rs 1000 · 4h · go out · nothing intense"]
  U --> MCPC["MCP Client / AI Orchestrator"]
  MCPC --> MCPS["MoodOS MCP Server<br/>tools: analyze_mood, extract_preferences,<br/>get_user_profile, retrieve_knowledge, ..."]

  MCPS --> S1

  subgraph S1["STEP 1 — Intent understanding"]
    I["Intent = relaxation / solo outing"]
  end

  S1 --> S2

  subgraph S2["STEP 2 — Mood Engine"]
    CM["Current = Exhausted"]
    DM["Desired = Relaxed + refreshed"]
    TR["Trajectory: Exhausted → Calm → Light entertainment → Refreshed"]
    EC["Emotional constraints: no high-intensity, no crowded peaks"]
  end

  S2 --> D1{Mem0 has relevant<br/>user memory?}

  D1 -->|Yes| S3
  D1 -->|No| S4

  subgraph S3["STEP 3 — Mem0  ·  what we know about THIS user"]
    M1["prefers budget-friendly experiences"]
    M2["enjoys movies"]
    M3["dislikes crowded places"]
    M4["likes quiet cafes"]
  end

  S3 --> S4

  subgraph S4["STEP 4 — Context Engine"]
    C1["Budget = Rs 1000"]
    C2["Duration = 4h"]
    C3["Social = Solo"]
    C4["Location = current"]
    C5["Intensity = Low"]
    C6["Weather = retrieved live"]
  end

  S4 --> D2{RAG confidence<br/>sufficient?}

  D2 -->|Yes| S5
  D2 -->|No — not a failure| API1

  subgraph S5["STEP 5 — RAG  ·  stable knowledge"]
    R1["relaxing movie themes"]
    R2["calming music characteristics"]
    R3["quiet-cafe descriptors"]
    R4["similar low-intensity experience patterns"]
  end

  S5 --> D3{Is live API data<br/>required?}
  D3 -->|Yes — showtimes, weather, ETA| S6
  D3 -->|No| S7

  API1["Structured APIs then web fallback"] -.-> S6

  subgraph S6["STEP 6 — Live APIs + Redis TTL"]
    L1["nearby cinemas + current showtimes"]
    L2["nearby restaurants / cafes"]
    L3["current weather"]
    L4["route / travel times"]
    L5["Do not embed seat availability"]
  end

  S6 --> S7

  subgraph S7["STEP 7 — Candidate generation"]
    MOV["Movies: low-intensity, well-reviewed, nearby showtime"]
    FOOD["Food: quiet cafes, comfort meals, under ~Rs 300"]
    PLC["Places: short walk, low-effort, nearby"]
    MUS["Music: calming playlist candidates"]
  end

  S7 --> S8

  subgraph S8["STEP 8 — Hard constraint filtering"]
    F1["DROP expensive > remaining budget"]
    F2["DROP far / high travel time"]
    F3["DROP unavailable showtimes"]
    F4["DROP crowded / high-intensity"]
    F5["DROP sequences exceeding 4h + travel"]
  end

  S8 --> D4{Candidates satisfy<br/>hard constraints?}
  D4 -->|No| S7
  D4 -->|Yes| D5{Sufficiently compatible<br/>with mood + Mem0?}
  D5 -->|No| DROP[Drop / replace item]
  D5 -->|Yes| S9

  subgraph S9["STEP 9 — Ranking then rerank"]
    SC["Score = MoodFit + PersonalPref + Context<br/>+ ReviewQuality + CrossDomain + Novelty<br/>− Distance − Violations"]
    RR["Rerank: diversity, quiet-compatible set,<br/>not 5 similar loud restaurants"]
  end

  S9 --> S10

  subgraph S10["STEP 10 — Experience Planner  ·  coherent sequence"]
    P1["20-min walk nearby"] --> P2["Quiet cafe"]
    P2 --> P3["Rs 300 comfort food"]
    P3 --> P4["Relaxing movie matching showtime"]
    P4 --> P5["Calming playlist afterward"]
    NOTE["Order respects: travel, budget split, hours, weather, Exhausted→Calm→Light→Refreshed"]
  end

  S10 --> S11

  subgraph S11["STEP 11 — Explanation"]
    X["Recommended because it matches low-energy mood,<br/>stays within Rs 1000, fits 4h, avoids crowded / high-intensity."]
  end

  S11 --> D6{Does the user<br/>want an action?}

  D6 -->|No| S13
  D6 -->|Yes| S12

  subgraph S12["STEP 12 — Optional action"]
    PR["prepare_movie_booking()"] --> SH["Show cinema, movie, time, price, seats"]
    SH --> D7{Explicit confirmation?}
    D7 -->|No| S13
    D7 -->|Yes| CF["confirm_movie_booking() via CinemaBookingProvider"]
  end

  S12 --> S13

  subgraph S13["STEP 13 — Feedback"]
    FB["User: That was perfect."]
    FB --> D8{Should this become<br/>long-term memory?}
    D8 -->|Repeated / high confidence| MEM["Mem0: enjoys low-intensity solo experiences after college"]
    D8 -->|Single occurrence| EVT["PostgreSQL event only — do not over-write profile"]
  end
```

---

## B2. How extracted values change filtering and ranking

```mermaid
flowchart LR
  subgraph EXTRACT["Extracted state"]
    E1["Mood = Exhausted"]
    E2["Desired = Relaxed"]
    E3["Budget = Rs 1000"]
    E4["Duration = 4h"]
    E5["Social = Solo"]
    E6["Intensity = Low"]
  end

  subgraph FILTER["Hard filters driven by values"]
    F1["Intensity=Low → drop clubs, horror jump-scare, packed concerts"]
    F2["Budget=1000 → drop premium tasting menus / far taxis"]
    F3["4h → drop long road trips + late last-show + long queues"]
    F4["Solo + Mem0 quiet-cafe → drop loud group venues"]
  end

  subgraph RANK["Ranking boosts"]
    R1["MoodFit: calm cafe, gentle walk, light film"]
    R2["Pref: movies + budget-friendly from Mem0"]
    R3["Context: nearby + weather-aware indoor if rain"]
    R4["Reviews: comforting, not exhausting pacing"]
    R5["Cross-domain: walk → cafe → film → playlist continuity"]
  end

  EXTRACT --> FILTER --> RANK
```

---

## B3. Example experience bundle (planner output)

```mermaid
flowchart TB
  START["T0  ·  Exhausted"] --> W["T0+20m  ·  nearby walk  ·  low effort  ·  Rs 0"]
  W --> C["Quiet cafe  ·  Mem0: likes quiet cafes  ·  not crowded"]
  C --> F["Comfort meal  ·  ~Rs 300  ·  remaining budget for tickets"]
  F --> M["Relaxing movie  ·  nearby cinema  ·  live showtime  ·  solo"]
  M --> P["Calming playlist  ·  Spotify authorized  ·  Desired=Refreshed"]
  P --> END["T0+~4h  ·  trajectory complete  ·  within Rs 1000"]
```

---

## B4. Grounding for this request (why not User → LLM → list)

| Question | System that answers | Not the LLM |
|---|---|---|
| Does this user hate crowds? | Mem0 | Would guess / forget |
| What themes fit “exhausted → calm”? | RAG / Mood Engine + RAG | Unstable catalog |
| What is playing *tonight nearby*? | Live cinema/showtime API + Redis | Would hallucinate times |
| Can we afford it in Rs 1000 including food? | Constraint filter + live prices | Would invent prices |
| Should we book? | User confirmation + CinemaBookingProvider | Must not auto-charge |
