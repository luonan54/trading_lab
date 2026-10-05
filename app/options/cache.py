from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
import threading
import time
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


@dataclass(frozen=True)
class CacheResult(Generic[V]):
    value: V
    hit: bool
    age_seconds: float


@dataclass
class _Entry(Generic[V]):
    value: V
    stored_at: float
    expires_at: float


class BoundedTTLCache(Generic[K, V]):
    """Thread-safe LRU TTL cache with per-key request coalescing."""

    def __init__(
        self,
        max_size: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be positive")
        self._max_size = max_size
        self._clock = clock
        self._entries: OrderedDict[K, _Entry[V]] = OrderedDict()
        self._loading: set[K] = set()
        self._condition = threading.Condition(threading.RLock())

    def __len__(self) -> int:
        with self._condition:
            self._remove_expired(self._clock())
            return len(self._entries)

    def _remove_expired(self, now: float) -> None:
        expired = [
            key
            for key, entry in self._entries.items()
            if entry.expires_at <= now
        ]
        for key in expired:
            self._entries.pop(key, None)

    def get(self, key: K) -> CacheResult[V] | None:
        with self._condition:
            now = self._clock()
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            return CacheResult(
                value=entry.value,
                hit=True,
                age_seconds=max(0.0, now - entry.stored_at),
            )

    def set(self, key: K, value: V, *, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        with self._condition:
            now = self._clock()
            self._remove_expired(now)
            self._entries[key] = _Entry(
                value=value,
                stored_at=now,
                expires_at=now + ttl_seconds,
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_size:
                self._entries.popitem(last=False)

    def get_or_load(
        self,
        key: K,
        *,
        ttl_seconds: float,
        loader: Callable[[], V],
    ) -> CacheResult[V]:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        with self._condition:
            while True:
                cached = self.get(key)
                if cached is not None:
                    return cached
                if key not in self._loading:
                    self._loading.add(key)
                    break
                self._condition.wait()

        loaded = False
        try:
            value = loader()
            loaded = True
        finally:
            if not loaded:
                with self._condition:
                    self._loading.remove(key)
                    self._condition.notify_all()

        with self._condition:
            self.set(key, value, ttl_seconds=ttl_seconds)
            self._loading.remove(key)
            self._condition.notify_all()
            return CacheResult(value=value, hit=False, age_seconds=0.0)

    def clear(self) -> None:
        with self._condition:
            self._entries.clear()


TTLCache = BoundedTTLCache
