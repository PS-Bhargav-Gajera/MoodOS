---
tags: [moodos, data-source, memory, storage]
---

# Local JSON Memory

The zero-cost memory fallback: `data/mem0_users.json` (`memory.py`, `LocalMemory`).

## Source

`LocalMemory` (`memory.py:90`):
- `retrieve` (`memory.py:110`) — scikit-learn **TF-IDF + cosine similarity** over
  memory texts; `ValueError` (single doc) → returns all `[:k]`.
- `add` (`memory.py:126`) — de-duplicates by (case-insensitive) exact text,
  writes with `created_at` + `confidence`.

**Bootstrapped demo memories** (`memory.py:45-51`): prefers budget-friendly
experiences, enjoys movies, dislikes crowded loud places, likes quiet cafés,
often watches movies alone.

## Behavior

Used whenever Mem0 Cloud is unset/unreachable (`Mem0Cloud.ok == False`); also
serves as a second source even when Cloud works (merged + de-duplicated in
`UserMemory.retrieve`, `memory.py:430-446`).

## Connects to

- [[Mem0]] · [[Get User Profile]] · [[Persistence]]

## Used by

- [[Request Flow]] · [[Architecture-Overview]]