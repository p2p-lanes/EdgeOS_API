from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Dict, Optional, Tuple

from app.core.utils import current_time


class WebhookCache:
    def __init__(self, expiry: timedelta = timedelta(hours=24)):
        self._cache: Dict[str, datetime] = {}
        self._expiry = expiry
        self._lock = Lock()

    def exists(self, fingerprint: str) -> bool:
        """Check if fingerprint exists and is not expired in a thread-safe manner"""
        with self._lock:
            self._clean_expired()
            return fingerprint in self._cache

    def add(self, fingerprint: str) -> bool:
        """
        Add fingerprint to cache if it doesn't exist.
        Returns True if fingerprint was added, False if it already existed.
        """
        with self._lock:
            self._clean_expired()
            if fingerprint in self._cache:
                return False
            self._cache[fingerprint] = current_time()
            return True

    def _clean_expired(self) -> None:
        """Remove expired fingerprints - already protected by lock in public methods"""
        expired = [
            k
            for k, timestamp in self._cache.items()
            if current_time() - timestamp > self._expiry
        ]
        for key in expired:
            del self._cache[key]


class TTLCache:
    """Generic TTL cache for any data type."""

    def __init__(self, expiry: timedelta = timedelta(minutes=10)):
        self._cache: Dict[str, Tuple[datetime, Any]] = {}
        self._expiry = expiry
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if it exists and hasn't expired."""
        with self._lock:
            self._clean_expired()
            if key in self._cache:
                _, value = self._cache[key]
                return value
            return None

    def set(self, key: str, value: Any) -> None:
        """Set a value in the cache with current timestamp."""
        with self._lock:
            self._cache[key] = (current_time(), value)

    def delete(self, key: str) -> None:
        """Delete a specific key from the cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]

    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self._cache.clear()

    def _clean_expired(self) -> None:
        """Remove expired entries - already protected by lock in public methods."""
        expired = [
            k
            for k, (timestamp, _) in self._cache.items()
            if current_time() - timestamp > self._expiry
        ]
        for key in expired:
            del self._cache[key]
