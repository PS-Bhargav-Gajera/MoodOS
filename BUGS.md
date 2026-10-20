# Bugs and tasks
Manual git tasks (untracked files, .gitignore, logs) are done outside
the agent. See PLAN.md phase 0.

## Open
- [ ] P1 app.py ~44 returns str(exc) to the client. Return a generic
      message, log the detail server-side.
- [ ] P1 35s LLM timeout (orchestrator.py ~483) abandons the thread
      without cancelling. Investigate; propose a fix before editing.
- [ ] P1 ip-api.com is called over plain HTTP (location.py ~69, ~74).
      The free tier may not support HTTPS. Verify first, then choose
      an HTTPS-capable alternative or accept the tradeoff.
- [ ] P2 Replace deprecated @app.on_event("startup") with lifespan.
- [ ] P2 Add TestClient tests for memory, journal, spotify, booking routes.
- [ ] P2 Add tests for chat.py.
- [ ] P2 Group budgets: "Rs5000 for 5 friends" is treated as Rs5000 total.
- [ ] P2 Tests make real network calls: two slow tests (28s and 18s) bypass
      conftest. It only blocks location_service. Investigate a broader
      guard (httpx or socket level). Propose before editing.
- [ ] P2 tool_usage["weather"] (orchestrator.py ~2338) says "Open-Meteo (live)"
      even when weather was unavailable. This violates the honesty rule.
- [ ] P3 test_pipeline writes to the real data/moodos.db. Use a temp DB
      (SQLITE_PATH via tmp_path) so tests never touch dev data.
- [ ] P3 Remove unused jinja2 dependency and dead chroma_dir config.
- [ ] P3 Move mid-file imports in app.py (~30-31) to the top.
- [ ] P3 Update .env.example with the 11 undocumented variables (names only).
- [ ] P3 Fix README run path (wrong folder).
- [ ] P3 Refresh moodos_obsidian notes that are stale
      (budget-fit-crash is already fixed).

## Done
- [x] P1 `/api/plan` returned 500 "cannot generate a plan" whenever RAG
      confidence was below the threshold, and the music + books legs were dead
      on every plan. `run_pipeline` called `search_music(q=...)`,
      `search_books(q=...)` and `search_web_knowledge(q=...)` while all three
      tools declare `query=`. The first two raise inside the parallel batch,
      which logs the TypeError and returns `[]` (silent empty legs while the
      panel still claimed "Spotify (live)"); the third sits outside every
      guard, so it escaped `run_pipeline` and killed the request. Fixed the
      keyword names, guarded the web fallback as an optional enrichment
      (recorded in `provider_errors`, never fatal), and made the `music` /
      `books` / `knowledge` provenance lines admit failure. Guard:
      `tests/test_mcp_call_signatures.py` parses `mcp.call(...)` sites with
      `ast` and checks them against the registered signatures, and the
      pipeline stubs now `bind()` against the real signatures instead of
      accepting `**kwargs`.
- [x] P1 Weather batch entry was redundant (sequential fetch is needed for
      the music query; the second call was a cache hit except when the first
      call failed, since the cache is only written on success). Removed the
      batch entry. Also removed a wrong-type fallback hazard.
