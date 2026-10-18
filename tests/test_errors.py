"""Tests for structured error codes, HTTP status mapping, and exception handlers."""

import pytest
from fastapi.testclient import TestClient
from app.connectors.mock import MockConnector
from app.connectors.registry import get_connector
from app.main import app
from app.models.errors import (
    ERROR_CODE_AUTH_EXPIRED,
    ERROR_CODE_CONTENT_REJECTED,
    ERROR_CODE_FREQUENCY_CAP,
    ERROR_CODE_QUOTA_EXHAUSTED,
    ERROR_CODE_RATE_LIMITED,
    ERROR_CODE_SPEC_VIOLATION,
    ERROR_CODE_IDEMPOTENCY_CONFLICT,
    ERROR_STATUS_MAP,
    AuthExpiredError,
    ConnectorException,
    ContentRejectedError,
    DestinationSpecViolationError,
    FrequencyCapExceededError,
    IdempotencyConflictError,
    QuotaExhaustedError,
    RateLimitedError,
)
from app.models.policy import DestinationPolicy
from app.services.policy_service import get_policy_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state() -> None:
    """Reset mock connector and policy service between tests."""
    connector = get_connector("mock")
    if isinstance(connector, MockConnector):
        connector.clear()
    get_policy_service().reset()


# --- Unit Tests for Exception Classes & HTTP Status Mappings ---


def test_error_status_mapping_table():
    """Verify standard HTTP status mapping for all required error codes."""
    assert ERROR_STATUS_MAP[ERROR_CODE_SPEC_VIOLATION] == 400
    assert ERROR_STATUS_MAP[ERROR_CODE_AUTH_EXPIRED] == 401
    assert ERROR_STATUS_MAP[ERROR_CODE_CONTENT_REJECTED] == 403
    assert ERROR_STATUS_MAP[ERROR_CODE_RATE_LIMITED] == 429
    assert ERROR_STATUS_MAP[ERROR_CODE_FREQUENCY_CAP] == 429
    assert ERROR_STATUS_MAP[ERROR_CODE_QUOTA_EXHAUSTED] == 429
    assert ERROR_STATUS_MAP[ERROR_CODE_IDEMPOTENCY_CONFLICT] == 409


def test_idempotency_conflict_exception():
    """Verify IdempotencyConflictError defaults to 409 Conflict and structured dict."""
    exc = IdempotencyConflictError("Key was reused with different payload.")
    assert exc.error_code == ERROR_CODE_IDEMPOTENCY_CONFLICT
    assert exc.status_code == 409
    data = exc.to_dict()
    assert data["error_code"] == ERROR_CODE_IDEMPOTENCY_CONFLICT
    assert data["message"] == "Key was reused with different payload."
    assert "detail" in data


def test_destination_spec_violation_exception():
    """Verify DestinationSpecViolationError defaults to 400 and structured dict."""
    exc = DestinationSpecViolationError("Text exceeds 280 chars.")
    assert exc.error_code == ERROR_CODE_SPEC_VIOLATION
    assert exc.status_code == 400
    data = exc.to_dict()
    assert data["error_code"] == ERROR_CODE_SPEC_VIOLATION
    assert data["message"] == "Text exceeds 280 chars."
    assert "detail" in data


def test_auth_expired_exception():
    """Verify AuthExpiredError defaults to 401 Unauthorized."""
    exc = AuthExpiredError()
    assert exc.error_code == ERROR_CODE_AUTH_EXPIRED
    assert exc.status_code == 401
    assert "expired" in exc.message


def test_content_rejected_exception():
    """Verify ContentRejectedError defaults to 403 Forbidden."""
    exc = ContentRejectedError("Spam filter triggered.")
    assert exc.error_code == ERROR_CODE_CONTENT_REJECTED
    assert exc.status_code == 403
    assert exc.message == "Spam filter triggered."


def test_rate_limited_exception():
    """Verify RateLimitedError defaults to 429 Too Many Requests."""
    exc = RateLimitedError()
    assert exc.error_code == ERROR_CODE_RATE_LIMITED
    assert exc.status_code == 429


def test_frequency_cap_exceeded_exception():
    """Verify FrequencyCapExceededError defaults to 429 Too Many Requests."""
    exc = FrequencyCapExceededError()
    assert exc.error_code == ERROR_CODE_FREQUENCY_CAP
    assert exc.status_code == 429


def test_quota_exhausted_exception():
    """Verify QuotaExhaustedError defaults to 429 Too Many Requests."""
    exc = QuotaExhaustedError()
    assert exc.error_code == ERROR_CODE_QUOTA_EXHAUSTED
    assert exc.status_code == 429


# --- API Integration Tests for All 6 Required Error Codes ---


def test_api_destination_spec_violation_code():
    """Verify API returns 400 and DESTINATION_SPEC_VIOLATION for invalid content."""
    response = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "   "}},
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error_code"] == ERROR_CODE_SPEC_VIOLATION
    assert "message" in data
    assert "detail" in data


def test_api_frequency_cap_exceeded_code():
    """Verify API returns 429 and FREQUENCY_CAP_EXCEEDED when publish rate is exceeded."""
    get_policy_service().set_policy(
        "mock",
        DestinationPolicy(destination_key="mock", max_requests_per_window=1, window_seconds=60),
    )

    # 1st publish succeeds
    res1 = client.post("/connector/v1/mock/publish", json={"content": {"text": "Allowed post"}})
    assert res1.status_code == 200

    # 2nd publish triggers frequency cap
    res2 = client.post("/connector/v1/mock/publish", json={"content": {"text": "Blocked post"}})
    assert res2.status_code == 429
    data = res2.json()
    assert data["error_code"] == ERROR_CODE_FREQUENCY_CAP
    assert "message" in data
    assert "detail" in data


def test_api_auth_expired_code():
    """Verify API returns 401 and AUTH_EXPIRED on simulated authentication expiration."""
    response = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Sample text", "simulate_error": "AUTH_EXPIRED"}},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["error_code"] == ERROR_CODE_AUTH_EXPIRED
    assert "expired" in data["message"].lower()
    assert "detail" in data


def test_api_rate_limited_code():
    """Verify API returns 429 and RATE_LIMITED on simulated downstream platform rate limit."""
    response = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Sample text", "simulate_error": "RATE_LIMITED"}},
    )
    assert response.status_code == 429
    data = response.json()
    assert data["error_code"] == ERROR_CODE_RATE_LIMITED
    assert "rate limit" in data["message"].lower()
    assert "detail" in data


def test_api_quota_exhausted_code():
    """Verify API returns 429 and QUOTA_EXHAUSTED on simulated quota exhaustion."""
    response = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Sample text", "simulate_error": "QUOTA_EXHAUSTED"}},
    )
    assert response.status_code == 429
    data = response.json()
    assert data["error_code"] == ERROR_CODE_QUOTA_EXHAUSTED
    assert "quota" in data["message"].lower()
    assert "detail" in data


def test_api_content_rejected_code():
    """Verify API returns 403 and CONTENT_REJECTED on simulated content rejection."""
    response = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Sample text", "simulate_error": "CONTENT_REJECTED"}},
    )
    assert response.status_code == 403
    data = response.json()
    assert data["error_code"] == ERROR_CODE_CONTENT_REJECTED
    assert "rejected" in data["message"].lower()
    assert "detail" in data


def test_api_set_simulated_error_on_connector_instance():
    """Verify MockConnector.set_simulated_error also triggers structured error via API."""
    connector = get_connector("mock")
    assert isinstance(connector, MockConnector)

    connector.set_simulated_error("AUTH_EXPIRED")
    response = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Test with connector-level simulated error"}},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == ERROR_CODE_AUTH_EXPIRED
