"""Unit and API integration tests for asynchronous background jobs and job status lookup."""

import pytest
from fastapi.testclient import TestClient
from app.connectors.mock import MockConnector
from app.connectors.registry import get_connector
from app.main import app
from app.models.errors import ERROR_CODE_IDEMPOTENCY_CONFLICT
from app.models.policy import DestinationPolicy
from app.services.idempotency_service import get_idempotency_service
from app.services.job_service import JobRecord, JobService, JobStatus, get_job_service
from app.services.policy_service import get_policy_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_system_state() -> None:
    """Reset mock connector store, policy limits, idempotency cache, and job records before each test."""
    connector = get_connector("mock")
    if isinstance(connector, MockConnector):
        connector.clear()
    get_policy_service().reset()
    get_idempotency_service().reset()
    get_job_service().reset()


# ==============================================================================
# 1. JobService Unit Tests
# ==============================================================================


def test_job_service_lifecycle():
    """Verify JobService creation, lookup, status updates, and reset."""
    service = JobService()

    # Create job
    job = service.create_job(connector_key="mock", payload={"text": "Test Job"})
    assert job.job_id.startswith("job_")
    assert job.status == JobStatus.QUEUED
    assert job.connector_key == "mock"
    assert job.payload == {"text": "Test Job"}
    assert job.result is None
    assert job.error is None

    # Retrieve job
    retrieved = service.get_job(job.job_id)
    assert retrieved is not None
    assert retrieved.job_id == job.job_id

    # Update to running
    service.update_status(job.job_id, JobStatus.RUNNING)
    assert service.get_job(job.job_id).status == JobStatus.RUNNING

    # Update to succeeded
    mock_result = {"id": "mock_123", "status": "published"}
    service.update_status(
        job.job_id,
        JobStatus.SUCCEEDED,
        result=mock_result,
        duration_ms=12.5,
    )
    completed = service.get_job(job.job_id)
    assert completed.status == JobStatus.SUCCEEDED
    assert completed.result == mock_result
    assert completed.duration_ms == 12.5
    assert completed.completed_at is not None

    # Reset
    service.reset()
    assert service.get_job(job.job_id) is None


def test_job_service_failure_transition():
    """Verify JobService transitions to failed with structured error payload."""
    service = JobService()
    job = service.create_job(connector_key="mock", payload={"text": "Fail test"})

    error_payload = {
        "error_code": "AUTH_EXPIRED",
        "message": "Token expired",
    }
    service.update_status(
        job.job_id,
        JobStatus.FAILED,
        error=error_payload,
        duration_ms=8.0,
    )

    failed_job = service.get_job(job.job_id)
    assert failed_job.status == JobStatus.FAILED
    assert failed_job.error == error_payload
    assert failed_job.duration_ms == 8.0


# ==============================================================================
# 2. API Async Job Submission & Status Lookup
# ==============================================================================


def test_async_publish_via_query_param_success():
    """Verify POST /connector/v1/mock/publish?async=true returns 202 Accepted and job succeeds."""
    response = client.post(
        "/connector/v1/mock/publish?async=true",
        json={"text": "Asynchronous background post"},
    )
    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "queued"
    assert data["connector_key"] == "mock"
    assert data["status_url"] == f"/connector/v1/jobs/{data['job_id']}"

    job_id = data["job_id"]

    # BackgroundTasks execute in TestClient; check status endpoint
    status_resp = client.get(f"/connector/v1/jobs/{job_id}")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["job_id"] == job_id
    assert status_data["status"] == "succeeded"
    assert status_data["result"] is not None
    assert status_data["result"]["success"] is True
    assert status_data["result"]["status"] == "published"
    post_id = status_data["result"]["id"]

    # Verify post exists in mock connector store
    get_resp = client.post(
        "/connector/v1/mock/get_status",
        json={"post_id": post_id},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == post_id


def test_async_publish_via_body_flag():
    """Verify async flag in request body triggers background processing."""
    response = client.post(
        "/connector/v1/mock/publish",
        json={
            "content": {"text": "Async via body flag"},
            "async": True,
        },
    )
    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "queued"

    job_id = data["job_id"]
    status_resp = client.get(f"/connector/v1/jobs/{job_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "succeeded"


def test_async_publish_via_prefer_header():
    """Verify 'Prefer: respond-async' header triggers background processing."""
    response = client.post(
        "/connector/v1/mock/publish",
        headers={"Prefer": "respond-async"},
        json={"text": "Async via Prefer header"},
    )
    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "queued"

    job_id = data["job_id"]
    status_resp = client.get(f"/connector/v1/jobs/{job_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "succeeded"


def test_async_publish_via_simulated_delay():
    """Verify operations with simulate_delay >= 2.0 trigger background processing automatically."""
    response = client.post(
        "/connector/v1/mock/publish",
        json={
            "text": "Long running simulation",
            "simulate_delay": 2.0,
        },
    )
    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data


def test_synchronous_publish_unaffected():
    """Verify standard publish without async flags remains completely synchronous (200 OK)."""
    response = client.post(
        "/connector/v1/mock/publish",
        json={"text": "Normal fast synchronous post"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "id" in data
    assert "job_id" not in data


def test_get_job_status_not_found():
    """Verify GET /connector/v1/jobs/{unknown_id} returns 404."""
    response = client.get("/connector/v1/jobs/job_unknown_999999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ==============================================================================
# 3. Async Job Failure Scenarios
# ==============================================================================


def test_async_job_failure_on_connector_exception():
    """Verify simulated connector exception updates job status to failed with structured error."""
    response = client.post(
        "/connector/v1/mock/publish?async=true",
        json={
            "text": "Simulate auth expiry",
            "simulate_error": "AUTH_EXPIRED",
        },
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    status_resp = client.get(f"/connector/v1/jobs/{job_id}")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["status"] == "failed"
    assert status_data["error"] is not None
    assert status_data["error"]["error_code"] == "AUTH_EXPIRED"


# ==============================================================================
# 4. Pre-execution Checks (Fast-Fail Without Job Creation)
# ==============================================================================


def test_async_publish_policy_violation_fails_fast():
    """Verify policy validation failure returns 400 immediately, before queueing a job."""
    policy_svc = get_policy_service()
    policy_svc.set_policy(
        "mock",
        DestinationPolicy(destination_key="mock", max_text_length=20),
    )

    response = client.post(
        "/connector/v1/mock/publish?async=true",
        json={"text": "This message is far too long for the destination policy"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "DESTINATION_SPEC_VIOLATION"
    # Ensure no background job was created
    assert len(get_job_service()._jobs) == 0


def test_async_publish_frequency_cap_fails_fast():
    """Verify frequency cap exhaustion returns 429 immediately, before queueing a job."""
    policy_svc = get_policy_service()
    policy_svc.set_policy(
        "mock",
        DestinationPolicy(destination_key="mock", max_requests_per_window=1, window_seconds=60),
    )

    # First request succeeds
    r1 = client.post(
        "/connector/v1/mock/publish?async=true",
        json={"text": "First allowed post"},
    )
    assert r1.status_code == 202

    # Second request hits frequency cap
    r2 = client.post(
        "/connector/v1/mock/publish?async=true",
        json={"text": "Second post blocked by frequency cap"},
    )
    assert r2.status_code == 429
    assert r2.json()["error_code"] == "FREQUENCY_CAP_EXCEEDED"


# ==============================================================================
# 5. Idempotency Interactions with Background Jobs
# ==============================================================================


def test_async_publish_idempotency_replay():
    """Verify replaying an async publish with the same Idempotency-Key returns the identical 202 and job_id."""
    key = "async-idem-key-1"
    payload = {"text": "Post with idempotency key"}

    r1 = client.post(
        "/connector/v1/mock/publish?async=true",
        headers={"Idempotency-Key": key},
        json=payload,
    )
    assert r1.status_code == 202
    job_id_1 = r1.json()["job_id"]

    # Replay request with exact same key and payload
    r2 = client.post(
        "/connector/v1/mock/publish?async=true",
        headers={"Idempotency-Key": key},
        json=payload,
    )
    assert r2.status_code == 202
    job_id_2 = r2.json()["job_id"]

    # Must be identical job ID and only 1 job created
    assert job_id_1 == job_id_2
    assert len(get_job_service()._jobs) == 1


def test_async_publish_idempotency_conflict():
    """Verify reusing the same Idempotency-Key with a different payload returns HTTP 409 Conflict."""
    key = "async-idem-key-conflict"

    r1 = client.post(
        "/connector/v1/mock/publish?async=true",
        headers={"Idempotency-Key": key},
        json={"text": "Original message"},
    )
    assert r1.status_code == 202

    # Reusing same key with different payload
    r2 = client.post(
        "/connector/v1/mock/publish?async=true",
        headers={"Idempotency-Key": key},
        json={"text": "Completely different message"},
    )
    assert r2.status_code == 409
    assert r2.json()["error_code"] == ERROR_CODE_IDEMPOTENCY_CONFLICT
