"""In-memory POST idempotency service with thread synchronization and TTL management."""

import hashlib
import json
import threading
import time
from typing import Any, Dict, Optional, Tuple
from app.config import get_settings
from app.models.errors import IdempotencyConflictError


class IdempotencyRecord:
    """Internal record tracking execution state, cached response, and safe reconciliation."""

    def __init__(self, request_hash: str) -> None:
        self.request_hash: str = request_hash
        self.response: Optional[Dict[str, Any]] = None
        self.created_at: float = time.time()
        self.is_completed: bool = False
        self.state: str = "in_flight"  # "in_flight", "completed", "outcome_unknown"
        self.metadata: Dict[str, Any] = {}
        self.event: threading.Event = threading.Event()


class IdempotencyService:
    """Service providing thread-safe in-memory POST idempotency tracking.

    NOTE ON STATE PERSISTENCE & IN-MEMORY LIMITATION:
    Idempotency records and concurrent request synchronization primitives are stored
    entirely IN-MEMORY within this process. State will reset upon application restart
    or when reset() is explicitly invoked. In a multi-replica or clustered deployment,
    a distributed coordinator or shared cache (such as Redis or Memcached) is required
    to synchronize idempotency keys across disparate instances.
    """

    def __init__(self, ttl_seconds: Optional[int] = None) -> None:
        """Initialize in-memory records, re-entrant synchronization lock, and TTL."""
        self._lock = threading.RLock()
        self._ttl_seconds: int = (
            ttl_seconds if ttl_seconds is not None else get_settings().IDEMPOTENCY_TTL_SECONDS
        )
        self._records: Dict[str, IdempotencyRecord] = {}

    def get_ttl(self) -> int:
        """Return the active idempotency TTL in seconds."""
        return self._ttl_seconds

    def set_ttl(self, ttl: int) -> None:
        """Dynamically configure the active TTL window in seconds (useful for tests)."""
        with self._lock:
            self._ttl_seconds = ttl

    def reset(self) -> None:
        """Clear all in-memory records and restore default TTL from application settings."""
        with self._lock:
            self._records.clear()
            self._ttl_seconds = get_settings().IDEMPOTENCY_TTL_SECONDS

    @staticmethod
    def compute_payload_hash(payload: Any) -> str:
        """Compute a deterministic SHA-256 fingerprint of the request payload."""
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _make_composite_key(self, connector_key: str, idempotency_key: str) -> str:
        """Generate a scoped composite key combining connector and idempotency identifiers."""
        return f"{connector_key.strip().lower()}::{idempotency_key.strip()}"

    def _prune_expired_locked(self) -> None:
        """Remove completed records whose lifetime exceeds the active TTL window.

        Must be called while holding self._lock.
        """
        now = time.time()
        expired_keys = [
            k
            for k, r in self._records.items()
            if r.is_completed and (now - r.created_at) > self._ttl_seconds
        ]
        for k in expired_keys:
            del self._records[k]

    def start_or_get(
        self,
        connector_key: str,
        idempotency_key: str,
        payload_hash: str,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Check idempotency record or reserve in-progress slot.

        Returns:
            Tuple of (is_cached, response_dict):
            - If is_cached is True, response_dict contains the original completed response.
            - If is_cached is False, the current thread owns the in-progress reservation and
              must subsequently call complete() on success or cancel() on failure.

        Raises:
            IdempotencyConflictError: If the same idempotency key is reused with a different
                                     request payload for this connector.
        """
        composite_key = self._make_composite_key(connector_key, idempotency_key)

        while True:
            with self._lock:
                self._prune_expired_locked()
                record = self._records.get(composite_key)

                if record is None:
                    # First request: claim the reservation
                    new_record = IdempotencyRecord(request_hash=payload_hash)
                    self._records[composite_key] = new_record
                    return False, None

                # Existing record found: verify payload matches
                if record.request_hash != payload_hash:
                    raise IdempotencyConflictError(
                        f"Idempotency key '{idempotency_key}' was reused with a different request payload "
                        f"for destination connector '{connector_key}'."
                    )

                if record.is_completed:
                    return True, record.response

                # Another thread is currently processing the exact same key & payload
                event = record.event

            # Wait outside the master lock for the in-progress thread to finish execution
            completed = event.wait(timeout=self._ttl_seconds)
            if not completed:
                # Timed out waiting for other thread: evict abandoned reservation and retry
                with self._lock:
                    if (
                        composite_key in self._records
                        and not self._records[composite_key].is_completed
                    ):
                        del self._records[composite_key]
                continue

    def mark_outcome_unknown(
        self,
        connector_key: str,
        idempotency_key: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Mark an idempotency reservation as outcome unknown (e.g. after platform timeout)."""
        composite_key = self._make_composite_key(connector_key, idempotency_key)
        with self._lock:
            record = self._records.get(composite_key)
            if record is not None:
                record.state = "outcome_unknown"
                if metadata:
                    record.metadata.update(metadata)
                record.event.set()

    def get_record(
        self,
        connector_key: str,
        idempotency_key: str,
    ) -> Optional[IdempotencyRecord]:
        """Retrieve idempotency record by connector and key."""
        composite_key = self._make_composite_key(connector_key, idempotency_key)
        with self._lock:
            return self._records.get(composite_key)

    def complete(
        self,
        connector_key: str,
        idempotency_key: str,
        response: Dict[str, Any],
    ) -> None:
        """Mark an in-progress idempotency reservation as completed with its response."""
        composite_key = self._make_composite_key(connector_key, idempotency_key)
        with self._lock:
            record = self._records.get(composite_key)
            if record is not None:
                record.response = response
                record.created_at = time.time()
                record.is_completed = True
                record.state = "completed"
                record.event.set()

    def cancel(self, connector_key: str, idempotency_key: str) -> None:
        """Cancel an in-progress reservation on error or validation failure."""
        composite_key = self._make_composite_key(connector_key, idempotency_key)
        with self._lock:
            record = self._records.get(composite_key)
            if record is not None and not record.is_completed:
                del self._records[composite_key]
                record.event.set()


# Global singleton instance for application runtime
_IDEMPOTENCY_SERVICE = IdempotencyService()


def get_idempotency_service() -> IdempotencyService:
    """Return the global IdempotencyService instance."""
    return _IDEMPOTENCY_SERVICE
