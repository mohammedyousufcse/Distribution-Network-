"""Unit and API integration tests for POST idempotency, duplicate suppression, and concurrency."""

import time
from concurrent.futures import ThreadPoolExecutor
from typing import List
import pytest
from fastapi.testclient import TestClient
from app.connectors.mock import MockConnector
from app.connectors.registry import get_connector
from app.main import app
from app.models.errors import ERROR_CODE_IDEMPOTENCY_CONFLICT, IdempotencyConflictError
from app.models.policy import DestinationPolicy
from app.services.idempotency_service import IdempotencyService, get_idempotency_service
from app.services.policy_service import get_policy_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_system_state() -> None:
    """Reset mock store, policy limits, and idempotency cache before each test."""
    connector = get_connector("mock")
    if isinstance(connector, MockConnector):
        connector.clear()
    get_policy_service().reset()
    get_idempotency_service().reset()


# ==============================================================================
# Unit Tests for IdempotencyService
# ==============================================================================


def test_idempotency_service_first_request_and_complete():
    """Verify first request acquires lock, and subsequent call with same hash returns cached response."""
    service = IdempotencyService(ttl_seconds=60)
    connector_key = "mock"
    key = "unit-test-key-1"
    payload = {"text": "Unit test content"}
    h = service.compute_payload_hash(payload)

    # 1. First request
    is_cached, cached_res = service.start_or_get(connector_key, key, h)
    assert is_cached is False
    assert cached_res is None

    # 2. Complete with simulated response
    mock_response = {"success": True, "id": "mock_abc123", "destination": "mock"}
    service.complete(connector_key, key, mock_response)

    # 3. Duplicate request with identical payload
    is_cached_2, cached_res_2 = service.start_or_get(connector_key, key, h)
    assert is_cached_2 is True
    assert cached_res_2 == mock_response


def test_idempotency_service_conflicting_payload_raises():
    """Verify reusing same key with different payload hash raises IdempotencyConflictError."""
    service = IdempotencyService(ttl_seconds=60)
    connector_key = "mock"
    key = "unit-test-conflict-key"

    h1 = service.compute_payload_hash({"text": "Original text"})
    h2 = service.compute_payload_hash({"text": "Altered conflicting text"})

    # First request completed
    is_cached, _ = service.start_or_get(connector_key, key, h1)
    assert is_cached is False
    service.complete(connector_key, key, {"id": "mock_001"})

    # Second request with different payload
    with pytest.raises(IdempotencyConflictError) as exc_info:
        service.start_or_get(connector_key, key, h2)

    assert exc_info.value.error_code == ERROR_CODE_IDEMPOTENCY_CONFLICT
    assert exc_info.value.status_code == 409


def test_idempotency_service_ttl_expiration():
    """Verify record expires and is pruned after TTL window."""
    service = IdempotencyService(ttl_seconds=1)
    connector_key = "mock"
    key = "unit-test-expire-key"
    payload = {"text": "Expiring text"}
    h = service.compute_payload_hash(payload)

    is_cached, _ = service.start_or_get(connector_key, key, h)
    assert is_cached is False
    service.complete(connector_key, key, {"id": "mock_expired"})

    # Wait for TTL to elapse
    time.sleep(1.1)

    # Next call with same key should be treated as a new request
    is_cached_after, _ = service.start_or_get(connector_key, key, h)
    assert is_cached_after is False


def test_idempotency_service_cancel_allows_retry():
    """Verify cancel() removes in-progress reservation so subsequent calls can retry."""
    service = IdempotencyService(ttl_seconds=60)
    connector_key = "mock"
    key = "unit-cancel-key"
    h = service.compute_payload_hash({"text": "Failing attempt"})

    # Claim reservation
    is_cached, _ = service.start_or_get(connector_key, key, h)
    assert is_cached is False

    # Simulate error and cancel
    service.cancel(connector_key, key)

    # Retry should succeed in claiming reservation again
    is_cached_retry, _ = service.start_or_get(connector_key, key, h)
    assert is_cached_retry is False


def test_idempotency_service_connector_isolation():
    """Verify same key used on different connectors is isolated."""
    service = IdempotencyService(ttl_seconds=60)
    key = "shared-key"
    h = service.compute_payload_hash({"text": "Content"})

    # Complete on 'mock'
    is_cached, _ = service.start_or_get("mock", key, h)
    assert is_cached is False
    service.complete("mock", key, {"id": "mock_id"})

    # Query with same key on 'other_connector'
    is_cached_other, _ = service.start_or_get("other_connector", key, h)
    assert is_cached_other is False


# ==============================================================================
# API Integration Tests
# ==============================================================================


def test_api_publish_without_idempotency_key_creates_distinct_posts():
    """Verify requests without an Idempotency-Key retain existing behavior and create distinct posts."""
    payload = {"content": {"text": "Non-idempotent announcement"}}

    res1 = client.post("/connector/v1/mock/publish", json=payload)
    assert res1.status_code == 200
    id1 = res1.json()["id"]

    res2 = client.post("/connector/v1/mock/publish", json=payload)
    assert res2.status_code == 200
    id2 = res2.json()["id"]

    # Must produce two different post IDs
    assert id1 != id2


def test_api_publish_first_request_with_idempotency_key():
    """Verify first publication with Idempotency-Key succeeds and returns standard payload."""
    payload = {"content": {"text": "First idempotent publish"}}
    headers = {"Idempotency-Key": "first-idem-key-001"}

    response = client.post("/connector/v1/mock/publish", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "id" in data
    assert data["id"].startswith("mock_")
    assert data["status"] == "published"


def test_api_publish_duplicate_request_returns_original_response():
    """Verify repeated publish with same key and payload returns identical response and post ID."""
    payload = {"content": {"text": "Guaranteed single publish"}}
    headers = {"Idempotency-Key": "duplicate-test-key-999"}

    # 1. Initial publish
    res1 = client.post("/connector/v1/mock/publish", json=payload, headers=headers)
    assert res1.status_code == 200
    data1 = res1.json()
    post_id = data1["id"]

    # 2. Duplicate publish
    res2 = client.post("/connector/v1/mock/publish", json=payload, headers=headers)
    assert res2.status_code == 200
    data2 = res2.json()

    # The duplicate must return the exact same post ID and response data
    assert data2["id"] == post_id
    assert data2["created_at"] == data1["created_at"]
    assert data2["destination"] == "mock"

    # Verify MockConnector only stored exactly 1 post
    connector = get_connector("mock")
    assert isinstance(connector, MockConnector)
    assert len(connector._posts) == 1


def test_api_publish_conflicting_payload_returns_409_conflict():
    """Verify reusing same key with different payload returns HTTP 409 and IDEMPOTENCY_CONFLICT."""
    headers = {"Idempotency-Key": "conflict-test-key-101"}

    # 1. Initial publish
    res1 = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Original message text."}},
        headers=headers,
    )
    assert res1.status_code == 200

    # 2. Replay with different payload
    res2 = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Modified conflicting message text."}},
        headers=headers,
    )
    assert res2.status_code == 409
    err_data = res2.json()
    assert err_data["error_code"] == ERROR_CODE_IDEMPOTENCY_CONFLICT
    assert "reused with a different request payload" in err_data["message"].lower()
    assert "detail" in err_data


def test_api_publish_idempotency_key_expiration():
    """Verify that after TTL expires, submitting with same key creates a new post."""
    # Temporarily set TTL to 1 second
    get_idempotency_service().set_ttl(1)
    headers = {"Idempotency-Key": "expiring-api-key-777"}
    payload = {"content": {"text": "Post before expiration"}}

    # 1. Publish before expiration
    res1 = client.post("/connector/v1/mock/publish", json=payload, headers=headers)
    assert res1.status_code == 200
    id1 = res1.json()["id"]

    # Wait for TTL to expire
    time.sleep(1.1)

    # 2. Publish after expiration with same key
    res2 = client.post("/connector/v1/mock/publish", json=payload, headers=headers)
    assert res2.status_code == 200
    id2 = res2.json()["id"]

    # Since TTL expired, a new post is created
    assert id1 != id2

    # Two posts exist in storage
    connector = get_connector("mock")
    assert isinstance(connector, MockConnector)
    assert len(connector._posts) == 2


def test_api_idempotent_replay_bypasses_frequency_cap():
    """Verify idempotent replay of an already published post does not consume or violate frequency cap."""
    policy_svc = get_policy_service()
    # Configure tight frequency cap of 1 request per 60s
    policy_svc.set_policy(
        "mock",
        DestinationPolicy(destination_key="mock", max_requests_per_window=1, window_seconds=60),
    )

    headers = {"Idempotency-Key": "freq-cap-bypass-key"}
    payload = {"content": {"text": "Sole allowed post"}}

    # 1. First publish succeeds and consumes frequency cap
    res1 = client.post("/connector/v1/mock/publish", json=payload, headers=headers)
    assert res1.status_code == 200
    original_id = res1.json()["id"]

    # 2. Idempotent replay with same key must succeed (200 OK) instead of 429 Too Many Requests
    res2 = client.post("/connector/v1/mock/publish", json=payload, headers=headers)
    assert res2.status_code == 200
    assert res2.json()["id"] == original_id

    # 3. A new request with a DIFFERENT key must be rejected by the frequency cap
    res3 = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Another post"}},
        headers={"Idempotency-Key": "different-key"},
    )
    assert res3.status_code == 429


def test_api_publish_concurrent_requests_produce_single_post():
    """Verify concurrent requests with same key cannot create duplicate posts (Requirement 6)."""
    headers = {"Idempotency-Key": "concurrent-single-post-key"}
    payload = {"content": {"text": "Concurrent stress test post"}}

    def make_request() -> dict:
        r = client.post("/connector/v1/mock/publish", json=payload, headers=headers)
        return {"status_code": r.status_code, "data": r.json()}

    # Execute 8 concurrent requests simultaneously
    num_requests = 8
    with ThreadPoolExecutor(max_workers=num_requests) as executor:
        futures = [executor.submit(make_request) for _ in range(num_requests)]
        results: List[dict] = [f.result() for f in futures]

    # All requests must return HTTP 200 OK
    assert all(r["status_code"] == 200 for r in results)

    # All requests must return the exact same post ID
    post_ids = {r["data"]["id"] for r in results}
    assert len(post_ids) == 1

    # Exactly 1 post must exist in MockConnector storage
    connector = get_connector("mock")
    assert isinstance(connector, MockConnector)
    assert len(connector._posts) == 1
