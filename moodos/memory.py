"""User memory: Mem0 Cloud when a key is set, plus a local fallback.

Mem0 answers "what do I know about THIS user?" — not domain RAG.

Every stored memory is tagged with a category from a small closed set so the
read path can filter what gets injected into a plan:

  preference  — durable tastes: cuisines, languages, activity types, social,
                budget band, intensity band (the SAME signal every time).
  episodic    — a record of what happened once: an accepted/rejected plan,
                a specific outing, a liked stop (used for continuity, never
                shoved at the planner as a standing rule).
  pattern     — recurring context: weekday cadence, rainy-day behaviour,
                time-of-day habits, "after college" routines.
  feedback    — explicit or explicit-adjacent ratings from the feedback flow.

Guardrails (see moodos/memory_writer.py): transient session state (the current
mood, this request's budget/time) is NEVER persisted as a preference.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from moodos.config import DATA_DIR, settings

log = logging.getLogger("moodos.memory")
MEM_PATH = DATA_DIR / "mem0_users.json"

MEMORY_CATEGORIES = ("preference", "episodic", "pattern", "feedback")

# Legacy "kind" values map onto a schema category — used to normalize records
# written before the category field existed (incl. the demo bootstrap seed).
_LEGACY_CATEGORY = {"long_term": "preference", "contextual": "episodic", "feedback": "feedback"}

BOOTSTRAP = [
    {"text": "Prefers budget-friendly experiences", "kind": "long_term", "confidence": 0.8, "category": "preference"},
    {"text": "Enjoys movies", "kind": "long_term", "confidence": 0.85, "category": "preference"},
    {"text": "Dislikes crowded loud places", "kind": "long_term", "confidence": 0.9, "category": "preference"},
    {"text": "Likes quiet cafes", "kind": "long_term", "confidence": 0.88, "category": "preference"},
    {"text": "Often watches movies alone", "kind": "long_term", "confidence": 0.7, "category": "preference"},
]


def normalize_record(rec: dict) -> dict:
    """Fill default schema fields on any record (old files, bootstrap, cloud rows)."""
    rec.setdefault("category", _LEGACY_CATEGORY.get(rec.get("kind", ""), "preference"))
    rec.setdefault("kind", "long_term" if rec.get("category") == "preference" else "contextual")
    rec.setdefault("confidence", 0.6)
    rec.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    if "metadata" not in rec or not isinstance(rec["metadata"], dict):
        rec["metadata"] = {}
    rec["metadata"].setdefault("category", rec["category"])
    rec.setdefault("source", "manual")
    return rec


def recency_scale(item: dict, half_life_days: float = 30.0) -> float:
    """Recency weight in [0, 1]; ~0.5 at half_life, decays from 1.0."""
    raw = item.get("created_at") or item.get("updated_at") or ""
    if not raw:
        return 0.8
    try:
        created = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return 0.8
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - created).total_seconds() / 86400.0
    if age_days < 0:
        return 1.0
    return max(0.0, 0.5 ** (age_days / half_life_days))


def blend_score(rec: dict, semantic: float, semantic_w: float = 0.7, recency_w: float = 0.3) -> float:
    """Combine semantic relevance and recency into one rankable score."""
    semantic = max(0.0, min(float(semantic), 1.0))
    return round(float(semantic_w) * semantic + float(recency_w) * recency_scale(rec), 4)


class LocalMemory:
    def __init__(self) -> None:
        self._users: dict[str, list[dict]] = {}
        if MEM_PATH.exists():
            try:
                self._users = json.loads(MEM_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Local memory file unreadable, starting fresh: %s", exc)
                self._users = {}
        if "demo" not in self._users:
            self._users["demo"] = [normalize_record({**b}) for b in BOOTSTRAP]
            self._save()

    def _save(self) -> None:
        MEM_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEM_PATH.write_text(json.dumps(self._users, indent=2, ensure_ascii=False), encoding="utf-8")

    def _records(self, user_id: str) -> list[dict]:
        return [normalize_record(rec) for rec in self._users.get(user_id, [])]

    def retrieve(self, user_id: str, query: str, k: int = 6,
                 categories: list[str] | None = None) -> list[dict]:
        memories = [m for m in self._records(user_id)
                    if not categories or m.get("category") in categories]
        if not memories:
            return []
        texts = [m["text"] for m in memories]
        vec = TfidfVectorizer()
        try:
            matrix = vec.fit_transform(texts + [query])
        except ValueError:
            return memories[:k]
        sims = cosine_similarity(matrix[-1], matrix[:-1])[0]
        ranked = sorted(zip(memories, sims), key=lambda x: blend_score(x[0], float(x[1]), 0.5, 0.5), reverse=True)
        return [{**m, "score": float(s), "source": "local"} for m, s in ranked[:k]]

    def add(self, user_id: str, text: str, kind: str = "long_term", confidence: float = 0.6,
            category: str | None = None, metadata: dict | None = None,
            source: str = "manual") -> bool:
        cat = category or _LEGACY_CATEGORY.get(kind, "preference")
        records = self._records(user_id)
        if any(m["text"].lower() == text.lower() for m in records):
            return False
        record: dict[str, Any] = {
            "id": uuid4().hex,
            "text": text,
            "kind": kind,
            "confidence": confidence,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "category": cat,
            "metadata": metadata or {},
            "source": source,
        }
        record["metadata"].setdefault("category", cat)
        self._users.setdefault(user_id, []).append(record)
        self._save()
        return True

    def _find_index(self, user_id: str, memory_id: str) -> int:
        for i, rec in enumerate(self._users.get(user_id, [])):
            if rec.get("id") == memory_id:
                return i
        return -1

    def list(self, user_id: str, categories: list[str] | None = None) -> list[dict]:
        records = self._records(user_id)
        if categories:
            records = [r for r in records if r.get("category") in categories]
        return sorted(records, key=lambda r: r.get("created_at", ""), reverse=True)

    def get(self, user_id: str, memory_id: str) -> dict | None:
        i = self._find_index(user_id, memory_id)
        return normalize_record(self._users[user_id][i]) if i >= 0 else None

    def update(self, user_id: str, memory_id: str, text: str | None = None,
               metadata: dict | None = None, confidence: float | None = None) -> bool:
        i = self._find_index(user_id, memory_id)
        if i < 0:
            return False
        rec = self._users[user_id][i]
        if text is not None:
            rec["text"] = text.strip()
        if metadata is not None:
            rec["metadata"] = {**rec.get("metadata", {}), **metadata}
        if confidence is not None:
            rec["confidence"] = confidence
        rec["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()
        return True

    def remove_one(self, user_id: str, memory_id: str) -> bool:
        i = self._find_index(user_id, memory_id)
        if i < 0:
            return False
        self._users[user_id].pop(i)
        self._save()
        return True

    def delete(self, user_id: str) -> int:
        removed = self._users.pop(user_id, [])
        if self._users:
            self._save()
        return len(removed)


class Mem0Cloud:
    BASE = "https://api.mem0.ai"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.ok = False
        self._headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._ping()

    def _ping(self) -> None:
        try:
            with httpx.Client(timeout=12.0) as client:
                r = client.get(f"{self.BASE}/v1/ping/", headers=self._headers)
            self.ok = r.status_code < 400
            if not self.ok:
                log.warning("Mem0 ping failed: %s", r.status_code)
        except Exception as exc:
            log.warning("Mem0 ping error: %s", exc)
            self.ok = False

    @staticmethod
    def _filters(user_id: str, categories: list[str] | None = None) -> dict:
        if categories:
            return {"AND": [{"user_id": user_id}, {"categories": {"in": list(categories)}}]}
        return {"user_id": user_id}

    @staticmethod
    def _row_to_record(row: dict) -> dict:
        """Shape a cloud row (v3 search/get_all shapes) into a local-style record."""
        meta = dict(row.get("metadata") or {})
        rec = {
            "id": row.get("id"),
            "text": row.get("memory") or row.get("text") or "",
            "created_at": row.get("created_at") or row.get("updated_at"),
            "updated_at": row.get("updated_at"),
            "metadata": meta,
            "category": meta.get("category") or (row.get("categories") or ["preference"])[0],
            "confidence": meta.get("confidence") or 0.8,
            "source": "mem0-cloud",
        }
        rec["kind"] = "long_term" if rec["category"] == "preference" else "contextual"
        return rec

    def search(self, user_id: str, query: str, k: int = 6,
               categories: list[str] | None = None) -> list[dict]:
        payloads = [
            (
                f"{self.BASE}/v3/memories/search/",
                {
                    "query": query,
                    "filters": self._filters(user_id, categories),
                    "top_k": k,
                    "rerank": False,
                },
            ),
            (
                f"{self.BASE}/v1/memories/search/",
                {"query": query, "user_id": user_id, "limit": k},
            ),
        ]
        for url, body in payloads:
            try:
                with httpx.Client(timeout=20.0) as client:
                    r = client.post(url, headers=self._headers, json=body)
                if r.status_code >= 400:
                    log.warning("Mem0 search %s -> %s", url, r.status_code)
                    continue
                data = r.json()
                rows = data.get("results") if isinstance(data, dict) else data
                if not isinstance(rows, list):
                    rows = data.get("memories", []) if isinstance(data, dict) else []
                out = []
                for row in rows[:k]:
                    if isinstance(row, str):
                        out.append({"text": row, "kind": "long_term", "score": 0.7,
                                    "source": "mem0-cloud", "category": "preference",
                                    "metadata": {"category": "preference"}, "id": None})
                        continue
                    rec = self._row_to_record(row)
                    if not rec["text"]:
                        continue
                    rec["score"] = float(row.get("score") or 0.7)
                    if categories and rec.get("category") not in categories:
                        continue
                    out.append(rec)
                return out
            except Exception as exc:
                log.warning("Mem0 search error: %s", exc)
        return []

    def add(self, user_id: str, text: str, metadata: dict | None = None,
            infer: bool = False) -> bool:
        """Write a memory with an explicit category/metadata tag.

        infer=False stores the text verbatim — WE own the content, Mem0 just
        stores it. The v3 add endpoint is async (returns a PENDING event), so a
        fresh write may take a moment to become searchable.
        """
        payloads = [
            (
                f"{self.BASE}/v3/memories/add/",
                {
                    "messages": [{"role": "user", "content": text}],
                    "user_id": user_id,
                    "metadata": metadata or {},
                    "infer": infer,
                },
            ),
            (
                f"{self.BASE}/v1/memories/",
                {"messages": [{"role": "user", "content": text}], "user_id": user_id},
            ),
        ]
        for url, body in payloads:
            try:
                with httpx.Client(timeout=20.0) as client:
                    r = client.post(url, headers=self._headers, json=body)
                if r.status_code < 400:
                    return True
                log.warning("Mem0 add %s -> %s", url, r.status_code)
            except Exception as exc:
                log.warning("Mem0 add error: %s", exc)
        return False

    def get_all(self, user_id: str, page_size: int = 100,
                categories: list[str] | None = None) -> list[dict]:
        attempts = [
            f"{self.BASE}/v3/memories/",
            f"{self.BASE}/v1/memories/",
        ]
        for url in attempts:
            try:
                params = {"filters": self._filters(user_id, categories)} if "v3" in url else {"user_id": user_id}
                with httpx.Client(timeout=25.0) as client:
                    if "v3" in url:
                        r = client.post(url, headers=self._headers,
                                        json=params, params={"page": 1, "page_size": page_size})
                    else:
                        r = client.get(url, headers=self._headers, params=params)
                if r.status_code >= 400:
                    log.warning("Mem0 get_all %s -> %s", url, r.status_code)
                    continue
                data = r.json()
                rows = data.get("results") if isinstance(data, dict) else []
                out = []
                for row in rows:
                    if isinstance(row, str):
                        continue
                    rec = self._row_to_record(row)
                    if not rec["text"]:
                        continue
                    rec["score"] = 0.9 if rec["category"] == "preference" else 0.7
                    out.append(rec)
                return out
            except Exception as exc:
                log.warning("Mem0 get_all error: %s", exc)
        return []

    def update(self, user_id: str, memory_id: str, text: str | None = None,
               metadata: dict | None = None) -> bool:
        if not memory_id:
            return False
        body: dict[str, Any] = {"user_id": user_id}
        if text is not None:
            body["text"] = text.strip()
        if metadata is not None:
            body["metadata"] = metadata
        try:
            with httpx.Client(timeout=20.0) as client:
                r = client.put(f"{self.BASE}/v1/memories/{memory_id}/", headers=self._headers, json=body)
            if r.status_code < 400:
                return True
            log.warning("Mem0 update %s -> %s", memory_id, r.status_code)
        except Exception as exc:
            log.warning("Mem0 update error: %s", exc)
        return False

    def remove_one(self, user_id: str, memory_id: str) -> bool:
        if not memory_id:
            return False
        try:
            with httpx.Client(timeout=20.0) as client:
                r = client.delete(f"{self.BASE}/v1/memories/{memory_id}/", headers=self._headers)
            if r.status_code < 400:
                return True
            log.warning("Mem0 remove_one %s -> %s", memory_id, r.status_code)
        except Exception as exc:
            log.warning("Mem0 remove_one error: %s", exc)
        return False

    def delete(self, user_id: str) -> bool:
        attempts = [
            (f"{self.BASE}/v1/memories/", "delete"),
            (f"{self.BASE}/v3/memories/delete/", "post"),
        ]
        for url, method in attempts:
            try:
                with httpx.Client(timeout=20.0) as client:
                    if method == "delete":
                        r = client.delete(url, headers=self._headers, json={"user_id": user_id})
                    else:
                        r = client.post(url, headers=self._headers, json={"filters": {"user_id": user_id}})
                if r.status_code < 400:
                    return True
                log.warning("Mem0 delete %s -> %s", url, r.status_code)
            except Exception as exc:
                log.warning("Mem0 delete error: %s", exc)
        return False


class UserMemory:
    def __init__(self) -> None:
        self.local = LocalMemory()
        self.cloud = Mem0Cloud(settings.mem0_api_key) if settings.mem0_api_key else None
        if self.cloud and self.cloud.ok:
            self._seed_cloud("demo")

    @property
    def cloud_ready(self) -> bool:
        return bool(self.cloud and self.cloud.ok)

    def _seed_cloud(self, user_id: str) -> None:
        existing = self.cloud.search(user_id, "preferences movies cafes", k=5) if self.cloud else []
        if existing:
            return
        blob = (
            "The user prefers budget-friendly experiences, enjoys movies, "
            "usually watches movies alone, likes quiet cafes, and dislikes crowded loud places."
        )
        self.cloud.add(user_id, blob, metadata={"category": "preference", "source": "seed"})

    def retrieve(self, user_id: str, query: str, k: int = 6,
                 categories: list[str] | None = None) -> list[dict]:
        cloud_hits = self.cloud.search(user_id, query, k=max(k, 8), categories=categories) if self.cloud_ready else []
        local_hits = self.local.retrieve(user_id, query, k=max(k, 8), categories=categories)
        seen: set[str] = set()
        merged: list[dict] = []
        for item in cloud_hits + local_hits:
            key = (item.get("text") or "").strip().lower()
            if not key or key in seen:
                continue
            if not item.get("score"):
                item["score"] = blend_score(item, 0.7)
            seen.add(key)
            merged.append(item)
            if len(merged) >= k:
                break
        return merged

    def add(self, user_id: str, text: str, kind: str = "long_term", confidence: float = 0.6,
            category: str | None = None, metadata: dict | None = None,
            source: str = "manual") -> bool:
        local_new = self.local.add(user_id, text, kind=kind, confidence=confidence,
                                   category=category, metadata=metadata, source=source)
        if self.cloud_ready and (category or kind) is not None:
            cloud_meta = dict(metadata or {})
            cloud_meta["category"] = category or _LEGACY_CATEGORY.get(kind, "preference")
            cloud_meta.setdefault("source", source)
            self.cloud.add(user_id, text, metadata=cloud_meta)
        return local_new

    def add_if_long_term(self, user_id: str, text: str, repeats: int) -> dict:
        if repeats < 2 and "today" in text.lower():
            return {"long_term": False, "new": False}
        if repeats >= 2 or (len(text) > 20 and "today" not in text.lower()):
            category = "feedback" if "enjoyed" in text.lower() or "liked" in text.lower() or "not a fan" in text.lower() \
                or "disliked" in text.lower() else "preference"
            is_new = self.add(user_id, text, kind="long_term", confidence=min(0.5 + 0.15 * repeats, 0.95),
                              category=category, source="feedback")
            return {"long_term": True, "new": is_new}
        self.add(user_id, text, kind="contextual", confidence=0.4, category="episodic", source="feedback")
        return {"long_term": False, "new": False}

    def list(self, user_id: str, categories: list[str] | None = None) -> list[dict]:
        cloud_items = self.cloud.get_all(user_id, page_size=100, categories=categories) if self.cloud_ready else []
        local_items = self.local.list(user_id, categories=categories)
        seen: set[str] = set()
        merged: list[dict] = []
        for item in cloud_items + local_items:
            key = (item.get("text") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged

    def update(self, user_id: str, memory_id: str, text: str | None = None,
               metadata: dict | None = None) -> bool:
        local_ok = self.local.update(user_id, memory_id, text=text, metadata=metadata)
        cloud_ok = self.cloud.update(user_id, memory_id, text=text, metadata=metadata) \
            if (self.cloud_ready and memory_id) else False
        return bool(local_ok or cloud_ok)

    def remove_one(self, user_id: str, memory_id: str) -> bool:
        local_ok = self.local.remove_one(user_id, memory_id)
        cloud_ok = self.cloud.remove_one(user_id, memory_id) if (self.cloud_ready and memory_id) else False
        return bool(local_ok or cloud_ok)

    def delete(self, user_id: str) -> dict:
        local_removed = self.local.delete(user_id)
        cloud_ok = self.cloud.delete(user_id) if self.cloud_ready else False
        return {"local": local_removed, "cloud": cloud_ok}


mem0 = UserMemory()