---
tags: [moodos, data-source, provider]
---

# Google-Books

Free Google Books API — the books provider ([[Search Books]]).

## Source

`providers.search_books` (`providers.py:809`):
`https://www.googleapis.com/books/v1/volumes?q=...&maxResults=limit`.

Items: `title`, `kind: book`, `text` (first 600 chars of description),
`themes` (categories), `estimated_cost: 0`, `duration_min: 0`.

Cached 6 h. The pipeline searches a fixed query `"comfort quiet contemporary"`
(`orchestrator.py:2191`).

## Connects to

- [[Search Books]] · [[TTL Cache]]

## Used by

- [[Request Flow]] (parallel lookups)