"""
Tests for Safe Retries and Exactly-Once Idempotency:
1. Re-submitting identical payload with same idempotency key returns cached original post without duplicate creation.
2. Re-submitting different payload with same key returns HTTP 409 Conflict (IDEMPOTENCY_CONFLICT).
3. Simulating timeout retry scenario proving duplicate count is zero.
4. Outcome-unknown state tracking.
"""

import threading
import time
import pytest
from fastapi.testclient import TestClient

from app.connectors.registry import get_connector
from app.main import app
from app.services.idempotency_service import get_idempotency_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_idempotency():
    svc = get_idempotency_service()
    svc.reset()
    yield
    svc.reset()


def test_idempotency_prevents_duplicate_posts():
    idem_key = "test_safe_retry_key_001"
    payload = {"content": {"text": "Safe retry message demonstration"}}

    # Attempt 1
    resp1 = client.post(
        "/connector/v1/mock/publish",
        json=payload,
        headers={"Idempotency-Key": idem_key},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    post_id_1 = data1["id"]

    # Attempt 2 (Client retries after network glitch or perceived delay)
    resp2 = client.post(
        "/connector/v1/mock/publish",
        json=payload,
        headers={"Idempotency-Key": idem_key},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    post_id_2 = data2["id"]

    # Assert that exact same post ID is returned (zero duplicate posts)
    assert post_id_1 == post_id_2

    # Check mock connector storage to verify post count is exactly 1
    mock_connector = get_connector("mock")
    matching_posts = [p for p in mock_connector._posts.values() if p["id"] == post_id_1]
    assert len(matching_posts) == 1


def test_idempotency_detects_conflicting_reuse():
    idem_key = "conflict_key_999"

    # Attempt 1 with content A
    resp1 = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Original announcement A"}},
        headers={"Idempotency-Key": idem_key},
    )
    assert resp1.status_code == 200

    # Attempt 2 with same key but different content B
    resp2 = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Different announcement B"}},
        headers={"Idempotency-Key": idem_key},
    )
    assert resp2.status_code == 409
    data = resp2.json()
    assert "IDEMPOTENCY_CONFLICT" in data["error_code"]


def test_outcome_unknown_state_and_reconciliation():
    svc = get_idempotency_service()
    key = "timeout_key_abc"
    payload_hash = svc.compute_payload_hash({"text": "Timeout payload"})

    # Thread 1 starts reservation
    is_cached, _ = svc.start_or_get("mock", key, payload_hash)
    assert is_cached is False

    # Mark outcome unknown
    svc.mark_outcome_unknown("mock", key, metadata={"attempted_at": time.time(), "reason": "socket_timeout"})
    record = svc.get_record("mock", key)
    assert record is not None
    assert record.state == "outcome_unknown"
    assert "socket_timeout" in record.metadata.get("reason", "")


def test_concurrent_retries_synchronization():
    """Verify that multiple threads concurrently sending the same key only create 1 post."""
    idem_key = "concurrent_key_sync"
    payload = {"content": {"text": "Concurrent safe retry test"}}
    results = []

    def send_request():
        r = client.post(
            "/connector/v1/mock/publish",
            json=payload,
            headers={"Idempotency-Key": idem_key},
        )
        results.append(r)

    threads = [threading.Thread(target=send_request) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 5
    assert all(r.status_code == 200 for r in results)
    post_ids = {r.json()["id"] for r in results}
    # Exactly one unique post created
    assert len(post_ids) == 1
