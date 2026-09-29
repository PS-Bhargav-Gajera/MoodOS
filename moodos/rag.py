from __future__ import annotations

import json
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from moodos.config import DATA_DIR
from moodos.db import log_knowledge

SEED_PATH = DATA_DIR / "seed_knowledge.json"
ACQUIRED_PATH = DATA_DIR / "acquired_knowledge.json"


class KnowledgeStore:
    """Stable knowledge RAG. TF-IDF local embeddings — zero API cost."""

    def __init__(self) -> None:
        self.docs: list[dict] = []
        self._vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
        self._matrix = None
        self.load_seed()

    def load_seed(self) -> None:
        docs: list[dict] = []
        if SEED_PATH.exists():
            docs.extend(json.loads(SEED_PATH.read_text(encoding="utf-8")))
        if ACQUIRED_PATH.exists():
            docs.extend(json.loads(ACQUIRED_PATH.read_text(encoding="utf-8")))
        # Music is never static: it always comes live from Spotify. Drop any
        # music doc (including a stale seed file on disk) so a fabricated
        # "playlist" can never reach the candidate pool.
        self.docs = [d for d in docs if d.get("kind") != "music"]
        self._fit()

    def _fit(self) -> None:
        texts = [self._text(d) for d in self.docs] or ["empty"]
        self._matrix = self._vectorizer.fit_transform(texts)

    def _text(self, doc: dict) -> str:
        parts = [
            doc.get("title", ""),
            doc.get("kind", ""),
            doc.get("text", ""),
            " ".join(doc.get("themes", [])),
            " ".join(doc.get("moods", [])),
        ]
        return " ".join(parts)

    def retrieve(self, query: str, k: int = 8, kinds: list[str] | None = None) -> tuple[list[dict], float]:
        if not self.docs or self._matrix is None:
            return [], 0.0
        q = self._vectorizer.transform([query])
        sims = cosine_similarity(q, self._matrix)[0]
        ranked = sorted(enumerate(sims), key=lambda x: x[1], reverse=True)
        hits = []
        scores = []
        for idx, score in ranked:
            doc = self.docs[idx]
            if kinds and doc.get("kind") not in kinds:
                continue
            hits.append({**doc, "score": float(score)})
            scores.append(float(score))
            if len(hits) >= k:
                break
        confidence = max(scores) if scores else 0.0
        return hits, confidence

    def ingest(self, doc: dict) -> str:
        key = doc.get("id") or f"{doc.get('kind')}:{doc.get('title')}".lower()
        existing = next((i for i, d in enumerate(self.docs) if d.get("id") == key or d.get("title") == doc.get("title")), None)
        doc = {**doc, "id": key}
        if existing is None:
            self.docs.append(doc)
            action = "insert"
        else:
            old = self.docs[existing]
            if old.get("text") == doc.get("text"):
                action = "ignore"
            else:
                self.docs[existing] = {**old, **doc}
                action = "update"
        if action != "ignore":
            self._fit()
            acquired = [d for d in self.docs if d.get("source") == "web-acquisition" or str(d.get("id", "")).startswith("web:")]
            ACQUIRED_PATH.write_text(json.dumps(acquired, indent=2, ensure_ascii=False), encoding="utf-8")
        log_knowledge(key, action)
        return action


knowledge = KnowledgeStore()
