---
tags: [moodos, core-logic, reviews]
---

# Review Classification

Keyword-rule sentiment/aspect classifier for movie/place candidates
(`moodos/mcp_server.py` `analyze_reviews`, and [[Analyze Reviews]]).

## Aspects

- `story` — positive when story/character/heart words appear, else mixed.
- `pacing` — slow when `slow`/`gentle`, else moderate.
- `tone` — calming when calm/quiet/warm/comfort words appear, else neutral.

`summary` = first 280 chars of the source text.

## Pipeline use

Applied to the top-4 ranked movie/place items after planning
(`orchestrator.py:2327-2330`); surfaced in the bundle as `reviews` for the
frontend cards. It is **not** the `review` score used by [[Ranking and
Scoring]] — that signal is the candidate's own `review_quality`/`vote`
(TMDB `vote_average`, `ranking.py:156`), and it is not a real NLP sentiment
model.

## Connects to

- [[Analyze Reviews]] · [[Ranking and Scoring]]

## Used by

- `run_pipeline` (`orchestrator.py:2327-2330`)
- [[Frontend]]