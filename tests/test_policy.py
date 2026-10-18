"""Unit and integration tests for destination policies, content validation, and frequency capping."""

import pytest
from fastapi.testclient import TestClient
from app.connectors.mock import MockConnector
from app.connectors.registry import get_connector
from app.main import app
from app.models.policy import (
    DestinationPolicy,
    ERROR_CODE_FREQUENCY_CAP,
    ERROR_CODE_SPEC_VIOLATION,
)
from app.services.policy_service import PolicyService, get_policy_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state() -> None:
    """Reset both the mock store and policy service before each test."""
    connector = get_connector("mock")
    if isinstance(connector, MockConnector):
        connector.clear()
    get_policy_service().reset()


# --- Unit Tests for Policy Model & Service ---


def test_destination_policy_model():
    """Verify DestinationPolicy model stores configurable constraints."""
    policy = DestinationPolicy(
        destination_key="custom_dest",
        max_text_length=140,
        max_requests_per_window=3,
        window_seconds=30,
    )
    assert policy.destination_key == "custom_dest"
    assert policy.max_text_length == 140
    assert policy.max_requests_per_window == 3
    assert policy.window_seconds == 30


def test_validate_valid_content_unit():
    """Verify validation passes when content meets length and format requirements."""
    service = PolicyService()
    result = service.validate_content("mock", {"text": "A compliant post."})
    assert result["valid"] is True
    assert "error" not in result


def test_validate_empty_text_unit():
    """Verify validation fails with DESTINATION_SPEC_VIOLATION when text is empty."""
    service = PolicyService()
    result = service.validate_content("mock", {"text": "   "})
    assert result["valid"] is False
    assert result["error_code"] == ERROR_CODE_SPEC_VIOLATION
    assert "non-empty 'text'" in result["error"]


def test_validate_text_exceeding_length_limit_unit():
    """Verify validation fails with DESTINATION_SPEC_VIOLATION when text exceeds max length."""
    service = PolicyService()
    # Configure tight limit of 20 characters
    service.set_policy(
        "mock",
        DestinationPolicy(destination_key="mock", max_text_length=20),
    )

    long_text = "This text is longer than twenty chars!"
    result = service.validate_content("mock", {"text": long_text})

    assert result["valid"] is False
    assert result["error_code"] == ERROR_CODE_SPEC_VIOLATION
    assert "exceeds maximum allowed limit" in result["error"]
    assert "20" in result["error"]


def test_frequency_cap_within_limit_unit():
    """Verify requests within the frequency cap are allowed."""
    service = PolicyService()
    service.set_policy(
        "mock",
        DestinationPolicy(
            destination_key="mock",
            max_requests_per_window=3,
            window_seconds=60,
        ),
    )

    for _ in range(3):
        res = service.check_and_record_publish("mock")
        assert res["allowed"] is True


def test_frequency_cap_exceeded_unit():
    """Verify request exceeding frequency cap is blocked with FREQUENCY_CAP_EXCEEDED."""
    service = PolicyService()
    service.set_policy(
        "mock",
        DestinationPolicy(
            destination_key="mock",
            max_requests_per_window=2,
            window_seconds=60,
        ),
    )

    # First two succeed
    assert service.check_and_record_publish("mock")["allowed"] is True
    assert service.check_and_record_publish("mock")["allowed"] is True

    # Third should be blocked
    third = service.check_and_record_publish("mock")
    assert third["allowed"] is False
    assert third["error_code"] == ERROR_CODE_FREQUENCY_CAP
    assert "rate limit exceeded" in third["error"]


def test_frequency_cap_reset_unit():
    """Verify reset() clears frequency cap tracking."""
    service = PolicyService()
    service.set_policy(
        "mock",
        DestinationPolicy(
            destination_key="mock",
            max_requests_per_window=1,
            window_seconds=60,
        ),
    )

    assert service.check_and_record_publish("mock")["allowed"] is True
    assert service.check_and_record_publish("mock")["allowed"] is False

    # After reset, publishing is allowed again
    service.reset()
    assert service.check_and_record_publish("mock")["allowed"] is True


# --- API Integration Tests for Policy Enforcement ---


def test_api_validate_text_exceeding_limit():
    """Verify POST /connector/v1/mock/validate reports spec violation for oversized text."""
    policy_svc = get_policy_service()
    policy_svc.set_policy(
        "mock",
        DestinationPolicy(destination_key="mock", max_text_length=30),
    )

    response = client.post(
        "/connector/v1/mock/validate",
        json={"content": {"text": "A string that is definitely longer than thirty characters."}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert data["error_code"] == ERROR_CODE_SPEC_VIOLATION
    assert "exceeds maximum allowed limit" in data["error"]


def test_api_publish_text_exceeding_limit_returns_400():
    """Verify POST /connector/v1/mock/publish returns 400 when text exceeds max length."""
    policy_svc = get_policy_service()
    policy_svc.set_policy(
        "mock",
        DestinationPolicy(destination_key="mock", max_text_length=15),
    )

    response = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "More than fifteen chars!"}},
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error_code"] == ERROR_CODE_SPEC_VIOLATION
    assert "exceeds maximum allowed limit" in data["detail"]


def test_api_frequency_cap_enforcement_returns_429():
    """Verify repeated publish requests exceeding limit return HTTP 429 FREQUENCY_CAP_EXCEEDED."""
    policy_svc = get_policy_service()
    policy_svc.set_policy(
        "mock",
        DestinationPolicy(
            destination_key="mock",
            max_requests_per_window=2,
            window_seconds=60,
        ),
    )

    # 1st publish - success
    res1 = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Publish 1"}},
    )
    assert res1.status_code == 200

    # 2nd publish - success
    res2 = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Publish 2"}},
    )
    assert res2.status_code == 200

    # 3rd publish - cap reached, should return 429 Too Many Requests
    res3 = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Publish 3"}},
    )
    assert res3.status_code == 429
    data = res3.json()
    assert data["error_code"] == ERROR_CODE_FREQUENCY_CAP
    assert "rate limit exceeded" in data["detail"]
