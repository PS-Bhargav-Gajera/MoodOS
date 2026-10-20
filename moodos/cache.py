"""Short-lived dynamic cache. Do not permanently embed live facts."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from moodos.config import settings

_lock = threading.Lock()


class TTLCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.cache_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._data = {}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._data), encoding="utf-8")

    def get(self, key: str) -> Any | None:
        with _lock:
            item = self._data.get(key)
            if not item:
                return None
            if item["expires"] < time.time():
                self._data.pop(key, None)
                self._save()
                return None
            return item["value"]

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        with _lock:
            self._data[key] = {"value": value, "expires": time.time() + ttl_seconds}
            self._save()

    def get_raw(self, key: str) -> Any | None:
        """Read a value ignoring its expiry (stale-copy reads only)."""
        with _lock:
            item = self._data.get(key)
            return None if not item else item["value"]


ttl_cache = TTLCache()
