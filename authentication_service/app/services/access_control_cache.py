from __future__ import annotations
import time


class SimpleCache:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._store: dict[tuple, tuple[float, object]] = {}

    def get(self, key):
        item = self._store.get(key)
        if not item:
            return None
        ts, value = item
        if time.time() - ts > self.ttl:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key, value):
        self._store[key] = (time.time(), value)

    def invalidate_prefix(self, prefix: tuple):
        keys = [k for k in self._store if k[: len(prefix)] == prefix]
        for k in keys:
            self._store.pop(k, None)
