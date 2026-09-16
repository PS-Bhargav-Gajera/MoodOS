# MoodOS

MCP-based AI orchestration: **mood + context + constraints → a coherent real-world experience**.

The LLM is not the database. Groq and Gemini only reason and call tools. Facts come from Mem0, RAG, and live APIs.

## Groq vs Gemini (what each agent does)

| Agent | Provider | Model (free tier) | Job |
|---|---|---|---|
| Extract / Mood / slots | **Groq** (first) | `openai/gpt-oss-20b` | Fast JSON: intent, mood, budget, time, intensity |
| Plan / explain | **Gemini** (first) | `gemini-2.5-flash` (fallbacks if renamed) | Experience sequence + grounded explanation |
| Fallback | The other provider, then local rules | — | App still runs with **no keys** using heuristics + seed knowledge |

Groq is used for speed (many small structured calls). Gemini is used for the longer planning pass. Neither is treated as ground truth for showtimes, weather, or prices.

## Zero-rupee stack

| Piece | Choice | Cost |
|---|---|---|
| App / MCP server | FastAPI (local) | Free |
| User memory (Mem0-style) | Local JSON + TF-IDF | Free |
| RAG | Local TF-IDF over seed + acquired docs | Free |
| Live weather | Open-Meteo | Free, no key |
| Places | OpenStreetMap Nominatim | Free, no key |
| Music | iTunes Search API | Free, no key |
| Books | Google Books | Free, no key |
| Movies (optional) | TMDB | Free key |
| Movies (default) | Seed + mock `CinemaBookingProvider` | Free |
| Web fallback | DuckDuckGo (`ddgs`) | Free |
| Cache | File TTL (Redis-shaped) | Free |
| App DB | SQLite | Free |
| Booking / food order | Mock providers + explicit confirm | Free |

You still need **free API keys** if you want the LLM agents (no credit card):

1. Groq: https://console.groq.com  
2. Gemini: https://aistudio.google.com/apikey  

Copy `.env.example` to `.env` and paste the keys. Leave them blank to demo the pipeline on heuristics.

## Run

```powershell
cd $env:USERPROFILE\Projects\MoodOS
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app:app --reload --port 8000
```

Open http://127.0.0.1:8000

## Architecture docs

- [Diagram A](docs/architecture/diagram-a-system-architecture.md)
- [Diagram B](docs/architecture/diagram-b-worked-example.md)

## What this is not

- Not `User → LLM → list of items`
- Not paid BookMyShow scraping
- Not “Mem0 eliminates hallucinations”
- Not “RAG trains the model”
