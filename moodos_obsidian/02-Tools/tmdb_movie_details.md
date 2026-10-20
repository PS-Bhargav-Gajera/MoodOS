---
tags: [moodos, tool, mcp]
---

# Tmdb Movie Details

MCP tool `tmdb_movie_details` → `lambda tmdb_id: providers.tmdb_movie_details(tmdb_id)`
(`moodos/mcp_server.py:41`).

## Signature

`tmdb_movie_details(tmdb_id: int) -> dict`

## Behavior

Full TMDB movie detail (`/movie/{id}` with `credits`): runtime, genres,
tagline, overview, top-5 cast, vote average, release date, poster
(`providers.py:1072`). Cached 24 h. No key → `{}`.

This is the real-runtime source used by [[Movie Metadata and Mood Fit]] via
`_tmdb_runtime_min` (`providers.py:1102`).

## Connects to

- [[TMDB]] · [[Movie Metadata and Mood Fit]] · [[TTL Cache]]

## Used by

- [[Search Home Movies]] (indirect, via watch providers + runtime)
- [[Movie Candidates]] / [[Movie Metadata and Mood Fit]]
- Public MCP surface