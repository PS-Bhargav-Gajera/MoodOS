# Diagram A — MoodOS Complete System Architecture

**One-sentence blueprint:** MoodOS is an MCP-based AI orchestration system that combines persistent user memory (Mem0), adaptive RAG, live external APIs, semantic retrieval, context-aware ranking, and experience planning to transform a user's emotional and situational state into a personalized real-world experience.

**Principle:** The LLM is an orchestrator/reasoner. It is not the database and not the source of truth.

```
LLM ≠ Database     RAG ≠ Training     Mem0 ≠ RAG     Live API ≠ Vector DB
MCP ≠ API Provider     Recommendation ≠ Action     Memory ≠ Ground Truth
```

---

## A0. Condensed end-to-end flow

```mermaid
flowchart TB
  U[User] --> C[MCP Client / AI Orchestrator]
  C --> S[MoodOS MCP Server]
  S --> IC[Intent + Context + Mood Engine]

  IC --> M[(Mem0<br/>this user)]
  IC --> R[(RAG / Vector DB<br/>domain knowledge)]
  IC --> L[Live APIs + Redis TTL]
  IC --> W[Web retrieval — fallback]

  M --> F[Candidate fusion]
  R --> F
  L --> F
  W --> F

  F --> SM[Semantic matching]
  SM --> CF{Hard constraints<br/>satisfied?}
  CF -->|No| DROP[Drop / substitute candidate]
  CF -->|Yes| RK[Context-aware ranking]
  RK --> RR[Reranking: diversity / novelty / compatibility]
  RR --> EP[Experience planner]
  EP --> EX[Explanation generator]
  EX --> U2[Personalized experience bundle]
  U2 --> ACT{User wants action?}
  ACT -->|No| FB[Feedback engine]
  ACT -->|Yes| PREP[PREPARE → show details]
  PREP --> CONF{Explicit confirmation?}
  CONF -->|No| FB
  CONF -->|Yes| EXEC[Execute authorized provider]
  EXEC --> FB
  FB --> MEMQ{Long-term memory?}
  MEMQ -->|Yes, high confidence / repeated| M
  MEMQ -->|No, contextual only| PG[(PostgreSQL events)]
```

---

## A1. Horizontal layers (system layout)

```mermaid
flowchart TB
  subgraph L1["LAYER 1 — USER INTERFACE"]
    WEB[Web] --- MOB[Mobile] --- CHAT[Chat]
  end

  subgraph L2["LAYER 2 — MCP CLIENT / AI ORCHESTRATOR"]
    IA[LLM intent analyzer]
    CA[Context analyzer]
    TR[Tool router]
    PL[Planning logic]
    IA --- CA --- TR --- PL
  end

  subgraph L3["LAYER 3 — MOODOS MCP SERVER  ·  standardized AI-facing capability interface"]
    TOOLS["Tools: executable capabilities"]
    RES["Resources: readable context"]
    PROMPTS["Prompts: reusable workflows"]
  end

  subgraph L4["LAYER 4 — INTERNAL INTELLIGENCE"]
    ME[Mood Engine]
    CE[Context Engine]
    RE[Recommendation Engine]
    RI[Review Intelligence]
    EP[Experience Planner]
    EE[Explanation Engine]
    FE[Feedback Engine]
  end

  subgraph L5["LAYER 5 — MEMORY + KNOWLEDGE"]
    MEM0[("Mem0 — user memory")]
    VDB[("Vector DB — Qdrant / pgvector")]
    PG[("PostgreSQL — app records")]
    REDIS[("Redis — short-lived cache")]
    NEO[("Optional Neo4j KG")]
  end

  subgraph L6["LAYER 6 — RETRIEVAL"]
    HYB[Hybrid retrieval]
    SEM[Semantic search]
    KW[Keyword / BM25]
    MF[Metadata filtering]
    WEB[Web retrieval]
    AF[Adaptive fallback]
    KA[Knowledge acquisition]
  end

  subgraph L7["LAYER 7 — EXTERNAL PROVIDERS  ·  not MCP servers"]
    TMDB[TMDB]
    SPOT[Spotify Web API]
    GB[Google Books]
    MAPS[Google Maps / Places]
    WX[Weather API]
    EV[Event APIs]
    FOOD[FoodOrderingProvider]
    CIN[CinemaBookingProvider]
  end

  subgraph L8["LAYER 8 — ACTIONS  ·  never paid without confirm"]
    PLAY[Playlist creation]
    NAV[Navigation]
    FORD[Food ordering]
    BOOK[Cinema booking]
  end

  L1 --> L2 --> L3 --> L4
  L4 --> L5
  L4 --> L6
  L6 --> L7
  L4 --> L8
  L8 --> L7
```

---

## A2. MCP architecture (correct model)

MCP is the **standardized AI-facing capability interface**. External APIs remain **providers** behind the MoodOS MCP server. They are not themselves MCP servers.

```mermaid
flowchart TB
  USER["User — Web / Mobile / Chat"] --> CLIENT["MCP Client / AI Orchestrator<br/>LLM reasons, routes tools, does not store truth"]

  CLIENT --> SERVER["MoodOS MCP Server"]

  subgraph SERVERBOX["MoodOS MCP Server"]
    T["TOOLS — executable"]
    R["RESOURCES — readable"]
    P["PROMPTS — workflows"]
  end

  SERVER --> T
  SERVER --> R
  SERVER --> P

  T --> INT["Internal services<br/>Mood / Context / Rank / Plan / Feedback"]
  T --> KNOW["Knowledge layer<br/>Mem0 · Vector DB · PostgreSQL · Redis · Neo4j"]
  T --> EXT["External providers<br/>TMDB · Spotify · Books · Maps · Weather · Events<br/>FoodOrderingProvider · CinemaBookingProvider"]

  R -.-> KNOW
  R -.-> EXT
```

### MCP Tools (executable)

| Tool | Role |
|---|---|
| `analyze_mood` | Current mood, desired mood, intensity, trajectory |
| `extract_preferences` | Explicit + implicit preference slots |
| `get_user_profile` | Authorized profile + preference snapshot |
| `search_movies` | TMDB-backed search (via provider adapter) |
| `search_books` | Google Books adapter |
| `search_music` | Spotify adapter |
| `search_restaurants` | Places / food provider adapter |
| `search_events` | Event provider adapter |
| `get_weather` | Weather provider + Redis TTL |
| `find_nearby_places` | Maps / Places |
| `retrieve_knowledge` | RAG / hybrid retrieval |
| `search_web_knowledge` | Adaptive web fallback |
| `rank_experiences` | Scoring + rerank |
| `build_experience` | Experience planner |
| `analyze_reviews` | Review intelligence |
| `create_playlist` | Authorized Spotify action |
| `prepare_movie_booking` | Draft booking — no charge |
| `confirm_movie_booking` | Execute only after explicit user confirmation |

### MCP Resources (readable context)

- `user://profile`
- `user://preferences`
- `movie://tmdb/{id}`
- `book://google/{id}`
- `experience://cozy-evening`
- `knowledge://mood/relaxation`

### MCP Prompts (reusable workflows)

- `/mood-night` · `/date-night` · `/study-session` · `/rainy-day` · `/weekend-plan` · `/stress-relief`

**Annotation:** MCP exists so the orchestrator calls a stable tool/resource/prompt contract instead of hard-wiring every vendor SDK into the prompt.

---

## A3. Three knowledge sources (must stay separate)

```mermaid
flowchart LR
  subgraph MEM["A. USER MEMORY — Mem0"]
    M1["What do I know about THIS USER?"]
    M2["Preferences · dislikes · past feedback<br/>behavioral patterns · recurring choices"]
    M3["Reduces memory-related hallucination<br/>Improves personalization"]
  end

  subgraph RAG["B. STABLE KNOWLEDGE — RAG"]
    R1["What do I know about movies, books,<br/>music, food, places, reviews?"]
    R2["Themes · descriptions · genres<br/>evergreen reviews · semantic relations"]
    R3["Embeddings + vector DB<br/>metadata filter + BM25<br/>optional knowledge graph"]
  end

  subgraph LIVE["C. DYNAMIC KNOWLEDGE — Live APIs"]
    L1["What is true RIGHT NOW?"]
    L2["Showtimes · seats · availability<br/>prices · weather · events · ETA"]
    L3["API → Redis cache → TTL<br/>Do not permanently embed"]
  end

  NOTE["Mem0 is not ground truth for live facts.<br/>Live APIs override stale memory about availability/price."]
```

### Mem0 examples (user-specific)

- Prefers psychological thrillers
- Usually avoids horror
- Likes quiet cafes
- Prefers budget-friendly experiences
- Often watches movies alone
- Disliked loud crowded places
- Previously enjoyed a particular experience type

**Do not claim:** Mem0 eliminates hallucinations.  
**Do claim:** Mem0 reduces memory-related errors by retrieving persistent user-specific facts.

---

## A4. Freshness model

```mermaid
flowchart TB
  subgraph STABLE["STABLE KNOWLEDGE — long-lived"]
    SA[API / web result] --> SN[Normalize + validate]
    SN --> SE[Embed]
    SE --> SV[("Vector DB")]
    SV --> SR[Long-term retrieval]
  end

  subgraph DYN["DYNAMIC KNOWLEDGE — short-lived"]
    DA[Live API] --> DR[("Redis")]
    DR --> TTL{TTL expired?}
    TTL -->|No| DC[Serve cached]
    TTL -->|Yes| RF[Refresh]
    RF --> DR
    RF --> DISC[Discard / update]
  end

  WARN["Do not permanently embed rapidly changing facts<br/>e.g. seat availability, live prices, current weather"]
```

**Annotation:** Redis exists so live facts stay fresh without polluting the vector index.

---

## A5. Adaptive retrieval / fallback (RAG miss is not failure)

```mermaid
flowchart TB
  Q[User query] --> ICE[Intent + context extraction]
  ICE --> M0[Retrieve user memory from Mem0]
  M0 --> D1{Mem0 has relevant<br/>user memory?}
  D1 -->|Yes| USEM[Attach user facts]
  D1 -->|No| RAG
  USEM --> RAG[Retrieve stable knowledge from RAG]

  RAG --> D2{RAG confidence<br/>sufficient?}
  D2 -->|Yes| USEK[Use retrieved knowledge]
  D2 -->|No| API[Query structured APIs — dashed fallback]

  API --> D3{Live API data<br/>required / still insufficient?}
  D3 -->|Facts are current-state| LIVE[Use API + Redis]
  D3 -->|Still insufficient| WEB[Web search / web retrieval]
  D3 -->|Sufficient| USEK

  LIVE --> USEK
  WEB --> ACQ[Knowledge acquisition path]
  ACQ --> USEK

  USEK --> LLM[LLM general knowledge as last resort]
  LLM --> D4{Still uncertain?}
  D4 -->|Yes| UNC[Explicitly represent uncertainty]
  D4 -->|No| CONT[Continue pipeline]

  style API stroke-dasharray: 5 5
  style WEB stroke-dasharray: 5 5
```

### Automatic knowledge acquisition (usage grows the index)

Retrieved data is **automatically ingested, normalized, validated, deduplicated, embedded, indexed, and made retrievable.** This is not “API data trains the RAG.” RAG is retrieval infrastructure, not model training.

```mermaid
flowchart TB
  EXT[External API / web result] --> NORM[Data normalization]
  NORM --> VAL[Validation]
  VAL --> ER[Entity resolution]
  ER --> DUP[Duplicate detection]
  DUP --> QC[Quality / relevance check]
  QC --> CLS[Classification]
  CLS --> CHK[Chunking]
  CHK --> EMB[Embedding model]
  EMB --> CMP{Existing entity?}

  CMP -->|New| INS[INSERT]
  CMP -->|Changed| UPD[UPDATE]
  CMP -->|Unchanged| IGN[IGNORE]

  INS --> VDB[("Vector DB")]
  UPD --> VDB
```

**Annotation:** A RAG miss triggers adaptive knowledge acquisition so the next similar query can retrieve instead of falling back.

---

## A6. Main internal pipeline + Mood / Context engines

```mermaid
flowchart TB
  REQ[USER REQUEST] --> NLU[Natural language understanding]
  NLU --> INT[Intent extraction]
  INT --> MOOD[Mood Engine]
  INT --> PREF[Preference extraction]
  INT --> CONS[Constraint extraction]
  INT --> CTX[Context Engine]

  subgraph MOODENG["MOOD ENGINE"]
    CS["Current state: stressed / tired / lonely / bored / excited / nostalgic / curious"]
    DS["Desired state: calm / refreshed / entertained / connected / energized / inspired"]
    TR["Trajectory example: Exhausted → calming music → comfort food → light movie → short walk → Relaxed"]
    OUT["Outputs: current mood · desired mood · intensity · trajectory · emotional constraints"]
  end

  subgraph CTXENG["CONTEXT ENGINE — influences ranking"]
    LOC[Location]
    TIME[Time]
    WX[Weather]
    BUD[Budget]
    DUR[Available duration]
    SOC[Social context]
    TRN[Transportation]
    INTN[Activity intensity]
    AVL[Current availability]
  end

  MOOD --> MOODENG
  CTX --> CTXENG

  MOODENG --> MEM[Mem0 retrieval]
  CTXENG --> MEM
  PREF --> MEM
  CONS --> MEM

  MEM --> RAG[RAG knowledge retrieval]
  RAG --> LIVE[Live API retrieval]
  LIVE --> FUS[Candidate fusion]
  FUS --> SEM[Semantic matching]
  SEM --> FIL{Hard constraints<br/>satisfied?}
  FIL -->|No| RM[Remove candidate]
  FIL -->|Yes| RANK[Context-aware ranking]
  RANK --> RR[Reranking]
  RR --> PLAN[Experience planner]
  PLAN --> BUN[Experience bundle]
  BUN --> EXP[Explanation generator]
  EXP --> USER[USER]
```

---

## A7. Recommendation engine (multi-stage)

```mermaid
flowchart TB
  subgraph GEN["1. CANDIDATE GENERATION"]
    A[APIs] --> C[Candidate pool]
    B[RAG] --> C
    W[Web retrieval] --> C
    H[User history] --> C
    S[Semantic similarity] --> C
  end

  subgraph MATCH["2. SEMANTIC MATCHING"]
    U["User: context + mood + preferences"]
    I["Item: movie / book / music / restaurant / place / event"]
    U --> SIM[Compatibility score]
    I --> SIM
  end

  subgraph HARD["3. HARD CONSTRAINT FILTERING"]
    F1[Budget]
    F2[Distance]
    F3[Duration]
    F4[Availability]
    F5[Age / content]
    F6[Opening hours]
    F7[Booking availability]
  end

  subgraph SCORE["4. RANKING — weights not frozen; can be learned later"]
    EQ["FinalScore =<br/>MoodMatch + UserPreference + ContextMatch<br/>+ ReviewQuality + CrossDomainCompatibility<br/>+ Novelty/Serendipity − Distance − ConstraintViolations"]
  end

  subgraph RERANK["5. RERANKING"]
    D[Diversity]
    N[Novelty]
    SER[Serendipity]
    X[Cross-domain compatibility]
    FB[User feedback signals]
    BC[Business constraints if any]
  end

  C --> MATCH --> HARD --> SCORE --> RERANK --> PLAN[Experience Planner]
```

**Annotation:** Reranking exists so the top list is a coherent *set*, not five near-duplicate items.

---

## A8. Review intelligence → ranking features

```mermaid
flowchart LR
  REV[Reviews] --> SA[Sentiment analysis]
  SA --> AE[Aspect extraction]
  AE --> TE[Theme extraction]
  TE --> SUM[Review summarization]
  SUM --> FEAT[Recommendation features]

  FEAT --> EX["Example movie:<br/>Story + · Acting strong · Pacing slow · Ending divisive · Music +"]
  FEAT --> RANK[Ranking engine]
  FEAT --> EXP[Explanation engine]
```

Example explanation: *Recommended because you usually prefer character-driven movies, and reviews indicate strong acting and emotional depth.*

---

## A9. Experience planner (key differentiator)

Does **not** dump isolated items (movie, book, song, restaurant). Builds a **coherent sequence**.

```mermaid
flowchart TB
  IN["Inputs: ranked candidates · mood trajectory · budget · duration<br/>travel times · opening hours · showtimes · weather · preferences"] --> P[Experience Planner]

  P --> ORD[Chronological order]
  P --> TRAV[Travel time]
  P --> BUD[Budget allocation]
  P --> HRS[Opening hours + showtimes]
  P --> WX[Weather]
  P --> EMO[Emotional progression]
  P --> PREF[User preferences]

  ORD --> BUN["Complete Experience Bundle"]
  TRAV --> BUN
  BUD --> BUN
  HRS --> BUN
  WX --> BUN
  EMO --> BUN
  PREF --> BUN

  BUN --> E1["1. 20-min nearby walk"]
  BUN --> E2["2. Quiet cafe"]
  BUN --> E3["3. Comfort meal under Rs 300"]
  BUN --> E4["4. Relaxing movie"]
  BUN --> E5["5. Calming playlist"]
```

**Annotation:** Experience planning exists because MoodOS recommends a *day/evening*, not a *catalog item*.

---

## A10. Action layer (recommendation ≠ execution)

```mermaid
flowchart TB
  REC["Recommendation: here is the best movie / meal / route"] --> WANT{Does the user<br/>want an action?}
  WANT -->|No| STOP[Stop at suggestion]
  WANT -->|Yes| PREP["prepare_*  e.g. prepare_movie_booking()"]

  PREP --> SHOW["Show details: cinema · movie · datetime · price · seats"]
  SHOW --> CONF{Has the user explicitly<br/>confirmed the paid action?}
  CONF -->|No| ABORT[Do not execute]
  CONF -->|Yes| AUTH["Tool permission + auth + ToS check"]
  AUTH --> EXEC["confirm_*  e.g. confirm_movie_booking()"]
  EXEC --> PROV["CinemaBookingProvider implementation:<br/>BookMyShowProvider IF authorized<br/>OtherAuthorizedProvider<br/>MockProvider"]

  NOTE["Same PREPARE → SHOW → CONFIRM → EXECUTE for food orders and paid activities.<br/>No unrestricted public booking API is assumed."]
```

**Annotation:** Booking requires confirmation because paid side-effects must never be implicit LLM tool fire.

---

## A11. Feedback loop (temporary vs long-term)

```mermaid
flowchart TB
  U[User] --> SIG["Like / Dislike / Skip / Modify / Book / Watch / Listen"]
  SIG --> FE[Feedback Engine]
  FE --> EXT[Memory extraction]
  EXT --> SPLIT{Should feedback become<br/>long-term memory?}

  SPLIT -->|Contextual / one-off| TMP["Temporary contextual preference<br/>e.g. no slow-paced movies TODAY"]
  SPLIT -->|Repeated / high confidence| LT["Long-term preference → Mem0"]

  TMP --> PG[("PostgreSQL recommendation events")]
  LT --> M0[("Mem0")]
  M0 --> FUT[Future recommendations]

  EX["User: I liked this movie but I don't want slow-paced movies today.<br/>Extract: movie liked · slow pacing disliked in current context"]
```

**Annotation:** Feedback goes to Mem0 only when it is a durable user fact, so one rainy-day exception does not rewrite the profile.

---

## A12. Data storage architecture

```mermaid
flowchart LR
  subgraph PG["PostgreSQL — structured app data"]
    P1[users]
    P2[preferences]
    P3[experiences]
    P4[recommendation events]
    P5[feedback]
    P6[API metadata]
  end

  subgraph M0["Mem0 — sensitive user memory"]
    M1[long-term personalized facts]
  end

  subgraph V["Vector DB — Qdrant or pgvector"]
    V1[documents · reviews · descriptions]
    V2[stable content · semantic relations]
  end

  subgraph R["Redis — TTL cache"]
    R1[showtimes · weather]
    R2[availability · prices · API responses]
  end

  subgraph N["Optional Neo4j"]
    N1["Movie → genre → theme → actor<br/>→ similar movie → compatible music<br/>→ compatible experience"]
  end
```

---

## A13. Security / trust boundaries

```mermaid
flowchart TB
  subgraph PUBLIC["Public / client"]
    UI[Web / Mobile / Chat]
  end

  subgraph AUTH["Authn / Authz boundary"]
    JWT[User authorization]
    RL[Rate limiting]
    IV[Input validation]
    TP[MCP tool permission checks]
  end

  subgraph SECRETS["Server-only"]
    SM[Secrets management]
    AP[Provider API authentication]
    TOS[Provider ToS compliance]
    ATTR[Source attribution]
  end

  subgraph SENS["Sensitive — authorization required"]
    MEM0[("Mem0 user memory")]
    PII[("PostgreSQL PII / events")]
  end

  subgraph PAID["Paid-action boundary"]
    CONF[Explicit confirmation]
  end

  UI --> AUTH --> SECRETS
  AUTH --> SENS
  AUTH --> PAID
```

---

## A14. Hallucination / reliability model (not zero hallucination)

```mermaid
flowchart TB
  LLM["LLM reasoning layer — orchestrator, not source of truth"] --> GND["Grounding layer"]

  subgraph GND["Grounding layer"]
    M[Mem0 — reduces memory-related errors]
    R[RAG — grounds stable knowledge]
    A[APIs — current facts]
    W[Web retrieval — knowledge gaps]
  end

  GND --> VAL["Validation layer"]

  subgraph VAL["Validation layer"]
    V[Validation of retrieved info]
    F[Freshness]
    C[Confidence thresholds / fallback]
    K[Hard constraints]
    U[Explicit uncertainty — no fabricated certainty]
  end
```

| Mechanism | What it actually does |
|---|---|
| Mem0 | Reduces memory-related errors; does not guarantee truth |
| RAG | Grounds stable domain knowledge at inference time |
| APIs | Authoritative current-state facts |
| Web retrieval | Fills RAG/API gaps |
| Validation | Checks retrieved information before planning |
| Confidence | Controls fallback, does not hide misses |
| Uncertainty | Prevents fabricated certainty |

---

## A15. Internal services vs knowledge vs providers

```mermaid
flowchart TB
  MCP["MoodOS MCP Server"] --> IS["Internal services"]
  MCP --> KL["Knowledge layer"]
  MCP --> EP["External providers"]

  IS --> ME[Mood Engine]
  IS --> CE[Context Engine]
  IS --> REC[Recommendation]
  IS --> RI[Review Intelligence]
  IS --> XP[Experience Planner]
  IS --> XE[Explanation]
  IS --> FB[Feedback]

  KL --> M0[("Mem0")]
  KL --> V[("Vector DB")]
  KL --> PG[("PostgreSQL")]
  KL --> RD[("Redis")]
  KL --> NEO[("Neo4j optional")]

  EP --> TMDB[TMDB]
  EP --> SP[Spotify]
  EP --> GB[Google Books]
  EP --> GM[Maps / Places]
  EP --> WX[Weather]
  EP --> EV[Events]
  EP --> FO["FoodOrderingProvider<br/>authorized / mock"]
  EP --> CB["CinemaBookingProvider<br/>authorized BMS / other / mock"]
```
