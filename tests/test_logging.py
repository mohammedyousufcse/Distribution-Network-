"""Unit and integration tests for structured JSON logging and security redaction."""

import json
import logging
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient
from app.connectors.mock import MockConnector
from app.connectors.registry import get_connector
from app.logging import JSONFormatter, redact_sensitive_data
from app.main import app
from app.models.errors import (
    ERROR_CODE_AUTH_EXPIRED,
    ERROR_CODE_FREQUENCY_CAP,
    ERROR_CODE_IDEMPOTENCY_CONFLICT,
    ERROR_CODE_SPEC_VIOLATION,
)
from app.models.policy import DestinationPolicy
from app.services.idempotency_service import get_idempotency_service
from app.services.policy_service import get_policy_service

client = TestClient(app)


class InMemoryLogHandler(logging.Handler):
    """Custom in-memory log handler capturing formatted JSON log lines."""

    def __init__(self) -> None:
        super().__init__()
        self.records: List[logging.LogRecord] = []
        self.formatted_lines: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.formatted_lines.append(self.format(record))


@pytest.fixture
def log_capture() -> InMemoryLogHandler:
    """Fixture providing an in-memory handler with JSONFormatter attached to the root logger."""
    handler = InMemoryLogHandler()
    handler.setFormatter(JSONFormatter())
    handler.setLevel(logging.DEBUG)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    yield handler
    root_logger.removeHandler(handler)


@pytest.fixture(autouse=True)
def clean_state() -> None:
    """Reset system state before each logging test."""
    connector = get_connector("mock")
    if isinstance(connector, MockConnector):
        connector.clear()
    get_policy_service().reset()
    get_idempotency_service().reset()


def parse_json_logs(handler: InMemoryLogHandler) -> List[Dict[str, Any]]:
    """Helper to parse all formatted lines into structured dicts."""
    parsed: List[Dict[str, Any]] = []
    for line in handler.formatted_lines:
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return parsed


# ==============================================================================
# Unit Tests for JSONFormatter and Redaction
# ==============================================================================


def test_json_formatter_produces_valid_json_with_base_fields():
    """Verify JSONFormatter generates valid JSON containing timestamp, level, logger, and message."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Test logging message",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    data = json.loads(formatted)

    assert "timestamp" in data
    assert data["level"] == "INFO"
    assert data["logger"] == "test.logger"
    assert data["message"] == "Test logging message"


def test_json_formatter_includes_extra_context_fields():
    """Verify contextual extra fields such as connector_key, operation, duration_ms are present."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="app.api.connector",
        level=logging.INFO,
        pathname=__file__,
        lineno=20,
        msg="Operation done",
        args=(),
        exc_info=None,
    )
    record.connector_key = "mock"
    record.operation = "publish"
    record.duration_ms = 45.67
    record.event = "operation_success"

    formatted = formatter.format(record)
    data = json.loads(formatted)

    assert data["connector_key"] == "mock"
    assert data["operation"] == "publish"
    assert data["duration_ms"] == 45.67
    assert data["event"] == "operation_success"


def test_sensitive_credentials_redaction():
    """Verify passwords, tokens, API keys, and Authorization headers are automatically redacted."""
    sensitive_dict = {
        "user": "test_user",
        "password": "supersecretpassword123",
        "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
        "api_key": "live_key_99999",
        "nested": {
            "client_secret": "secret_abc",
            "safe_field": "public_value",
        },
    }
    redacted = redact_sensitive_data(sensitive_dict)

    assert redacted["user"] == "test_user"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["access_token"] == "[REDACTED]"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["client_secret"] == "[REDACTED]"
    assert redacted["nested"]["safe_field"] == "public_value"

    # Also test Bearer string redaction
    bearer_msg = "Received Authorization: Bearer abc123secrettoken in header"
    assert "Bearer [REDACTED]" in redact_sensitive_data(bearer_msg)


# ==============================================================================
# API Integration Tests for Structured Logging Events
# ==============================================================================


def test_api_publish_logs_operation_start_and_success(log_capture: InMemoryLogHandler):
    """Verify successful publish logs operation_start and operation_success with duration and post_id."""
    payload = {"content": {"text": "Publish logging test"}}
    response = client.post("/connector/v1/mock/publish", json=payload)
    assert response.status_code == 200

    logs = parse_json_logs(log_capture)
    start_logs = [l for l in logs if l.get("event") == "operation_start"]
    success_logs = [l for l in logs if l.get("event") == "operation_success"]

    assert len(start_logs) >= 1
    start = start_logs[0]
    assert start["connector_key"] == "mock"
    assert start["method"] == "publish"
    assert start["operation"] == "publish"

    assert len(success_logs) >= 1
    success = success_logs[0]
    assert success["connector_key"] == "mock"
    assert success["method"] == "publish"
    assert success["operation"] == "publish"
    assert "duration_ms" in success
    assert isinstance(success["duration_ms"], (int, float))
    assert "post_id" in success


def test_api_policy_validation_failure_logging(log_capture: InMemoryLogHandler):
    """Verify policy validation failure logs policy_validation_failure with DESTINATION_SPEC_VIOLATION."""
    # Empty text triggers policy spec violation
    response = client.post("/connector/v1/mock/publish", json={"content": {"text": "   "}})
    assert response.status_code == 400

    logs = parse_json_logs(log_capture)
    policy_logs = [l for l in logs if l.get("event") == "policy_validation_failure"]

    assert len(policy_logs) >= 1
    p_log = policy_logs[0]
    assert p_log["connector_key"] == "mock"
    assert p_log["operation"] == "publish"
    assert p_log["error_code"] == ERROR_CODE_SPEC_VIOLATION
    assert "duration_ms" in p_log


def test_api_frequency_cap_rejection_logging(log_capture: InMemoryLogHandler):
    """Verify frequency cap violation logs frequency_cap_exceeded with FREQUENCY_CAP_EXCEEDED."""
    policy_svc = get_policy_service()
    policy_svc.set_policy(
        "mock",
        DestinationPolicy(destination_key="mock", max_requests_per_window=1, window_seconds=60),
    )

    # 1st publish succeeds
    client.post("/connector/v1/mock/publish", json={"content": {"text": "Post 1"}})
    # 2nd publish rejected
    res2 = client.post("/connector/v1/mock/publish", json={"content": {"text": "Post 2"}})
    assert res2.status_code == 429

    logs = parse_json_logs(log_capture)
    freq_logs = [l for l in logs if l.get("event") == "frequency_cap_exceeded"]

    assert len(freq_logs) >= 1
    f_log = freq_logs[0]
    assert f_log["connector_key"] == "mock"
    assert f_log["operation"] == "publish"
    assert f_log["error_code"] == ERROR_CODE_FREQUENCY_CAP
    assert "duration_ms" in f_log


def test_api_idempotency_conflict_logging(log_capture: InMemoryLogHandler):
    """Verify idempotency conflict logs idempotency_conflict with IDEMPOTENCY_CONFLICT."""
    headers = {"Idempotency-Key": "log-conflict-key"}
    # 1st publish
    client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Original text"}},
        headers=headers,
    )
    # 2nd publish with conflicting payload
    res2 = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Conflicting different text"}},
        headers=headers,
    )
    assert res2.status_code == 409

    logs = parse_json_logs(log_capture)
    conflict_logs = [l for l in logs if l.get("event") == "idempotency_conflict"]

    assert len(conflict_logs) >= 1
    c_log = conflict_logs[0]
    assert c_log["connector_key"] == "mock"
    assert c_log["operation"] == "publish"
    assert c_log["error_code"] == ERROR_CODE_IDEMPOTENCY_CONFLICT
    assert c_log["status_code"] == 409
    assert "duration_ms" in c_log


def test_api_connector_exception_logging(log_capture: InMemoryLogHandler):
    """Verify connector exception (AUTH_EXPIRED) logs connector_exception with error_code and status."""
    response = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Sample text", "simulate_error": "AUTH_EXPIRED"}},
    )
    assert response.status_code == 401

    logs = parse_json_logs(log_capture)
    exc_logs = [l for l in logs if l.get("event") == "connector_exception"]

    assert len(exc_logs) >= 1
    e_log = exc_logs[0]
    assert e_log["error_code"] == ERROR_CODE_AUTH_EXPIRED
    assert e_log["status_code"] == 401
