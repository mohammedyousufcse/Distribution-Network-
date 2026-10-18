"""In-memory background job tracking service for asynchronous connector operations."""

import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class JobStatus(str, Enum):
    """Execution status states for background operations."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobRecord:
    """Internal model representing an asynchronous background task execution."""

    def __init__(
        self,
        job_id: str,
        connector_key: str,
        payload: Optional[Dict[str, Any]] = None,
        payload_hash: Optional[str] = None,
    ) -> None:
        self.job_id = job_id
        self.connector_key = connector_key
        self.status = JobStatus.QUEUED
        now_iso = datetime.now(timezone.utc).isoformat()
        self.created_at = now_iso
        self.updated_at = now_iso
        self.completed_at: Optional[str] = None
        self.duration_ms: Optional[float] = None
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[Dict[str, Any]] = None
        self.payload = payload
        self.payload_hash = payload_hash

    def to_dict(self) -> Dict[str, Any]:
        """Serialize job record to dictionary format."""
        return {
            "job_id": self.job_id,
            "status": self.status.value if isinstance(self.status, JobStatus) else str(self.status),
            "connector_key": self.connector_key,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "result": self.result,
            "error": self.error,
        }


class JobService:
    """Thread-safe in-memory manager for tracking asynchronous background jobs.

    NOTE ON STATE PERSISTENCE & IN-MEMORY LIMITATION:
    Job records are maintained strictly IN-MEMORY within this single application process.
    State will NOT survive container/process restarts and is not shared across multiple
    distributed replicas. In an enterprise clustered architecture, a distributed worker
    framework (e.g. Celery / RQ backed by Redis or PostgreSQL) would be required.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: Dict[str, JobRecord] = {}

    def create_job(
        self,
        connector_key: str,
        payload: Optional[Dict[str, Any]] = None,
        payload_hash: Optional[str] = None,
    ) -> JobRecord:
        """Create and register a new queued background job."""
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        record = JobRecord(
            job_id=job_id,
            connector_key=connector_key.strip().lower(),
            payload=payload,
            payload_hash=payload_hash,
        )
        with self._lock:
            self._jobs[job_id] = record
        return record

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Retrieve a job record by its identifier."""
        with self._lock:
            return self._jobs.get(job_id.strip())

    def update_status(
        self,
        job_id: str,
        status: JobStatus | str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
    ) -> Optional[JobRecord]:
        """Update status, timestamps, and payload results for an existing job."""
        with self._lock:
            record = self._jobs.get(job_id.strip())
            if record is not None:
                record.status = status if isinstance(status, JobStatus) else JobStatus(str(status))
                now_iso = datetime.now(timezone.utc).isoformat()
                record.updated_at = now_iso
                if record.status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
                    record.completed_at = now_iso
                if result is not None:
                    record.result = result
                if error is not None:
                    record.error = error
                if duration_ms is not None:
                    record.duration_ms = duration_ms
            return record

    def reset(self) -> None:
        """Clear all stored job records (useful for test isolation)."""
        with self._lock:
            self._jobs.clear()


# Global singleton instance for application runtime
_JOB_SERVICE = JobService()


def get_job_service() -> JobService:
    """Return the global JobService singleton."""
    return _JOB_SERVICE
