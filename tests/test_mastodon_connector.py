"""Automated unit and API integration tests for the real Mastodon connector."""

import json
from typing import Any, Dict
import httpx
import pytest
from fastapi.testclient import TestClient
from app.connectors.base import BaseConnector
from app.connectors.mastodon import MASTODON_MAX_LENGTH, MastodonConnector
from app.connectors.registry import get_available_connectors, get_connector, register_connector
from app.logging import redact_sensitive_data
from app.main import app
from app.models.errors import (
    AuthExpiredError,
    ContentRejectedError,
    DestinationError,
    DestinationSpecViolationError,
    ForbiddenError,
    NetworkError,
    RateLimitedError,
)
from app.services.idempotency_service import get_idempotency_service
from app.services.job_service import get_job_service
from app.services.policy_service import get_policy_service

client = TestClient(app)

TEST_BASE_URL = "https://mastodon.example.com"
TEST_TOKEN = "test_mastodon_access_token_secret_xyz123"


@pytest.fixture(autouse=True)
def clean_state():
    """Reset services and registry state between tests."""
    get_policy_service().reset()
    get_idempotency_service().reset()
    get_job_service().reset()
    # Reset registry mastodon connector to fresh instance
    register_connector(
        "mastodon",
        MastodonConnector(base_url=TEST_BASE_URL, access_token=TEST_TOKEN),
    )


# ==============================================================================
# 1. Unit Tests: Initialization & Configuration Validation
# ==============================================================================


def test_mastodon_inherits_base_connector():
    """Verify MastodonConnector is an instance of BaseConnector."""
    connector = MastodonConnector(base_url=TEST_BASE_URL, access_token=TEST_TOKEN)
    assert isinstance(connector, BaseConnector)


def test_mastodon_registry_membership():
    """Verify 'mastodon' is registered and available alongside 'mock'."""
    connectors = get_available_connectors()
    assert "mock" in connectors
    assert "mastodon" in connectors
    assert isinstance(get_connector("mastodon"), MastodonConnector)


def test_missing_base_url_raises_spec_violation():
    """Verify unconfigured base URL raises DestinationSpecViolationError."""
    connector = MastodonConnector(base_url="", access_token=TEST_TOKEN)
    with pytest.raises(DestinationSpecViolationError) as exc_info:
        connector.publish({"text": "Test post"})
    assert "base URL is missing" in str(exc_info.value)


def test_insecure_http_url_rejected_by_default():
    """Verify non-HTTPS external URL is rejected for security."""
    connector = MastodonConnector(
        base_url="http://insecure.mastodon.instance",
        access_token=TEST_TOKEN,
    )
    with pytest.raises(DestinationSpecViolationError) as exc_info:
        connector.publish({"text": "Test post"})
    assert "must use HTTPS" in str(exc_info.value)


def test_localhost_http_allowed_for_testing():
    """Verify localhost/127.0.0.1/testserver HTTP URLs are permitted for local tests."""
    mock_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"id": "1", "url": "http://localhost/statuses/1"})
    )
    connector = MastodonConnector(
        base_url="http://localhost:8000",
        access_token=TEST_TOKEN,
        http_client=httpx.Client(transport=mock_transport),
    )
    res = connector.publish({"text": "Local test"})
    assert res["success"] is True


def test_missing_access_token_raises_auth_error():
    """Verify unconfigured access token raises AuthExpiredError."""
    connector = MastodonConnector(base_url=TEST_BASE_URL, access_token="")
    with pytest.raises(AuthExpiredError) as exc_info:
        connector.publish({"text": "Test post"})
    assert "access token is missing" in str(exc_info.value)


# ==============================================================================
# 2. Content Validation Tests
# ==============================================================================


def test_content_validation():
    """Verify content validation for length and structure constraints."""
    connector = MastodonConnector(base_url=TEST_BASE_URL, access_token=TEST_TOKEN)

    # Valid content
    assert connector.validate({"text": "Valid short text"})["valid"] is True

    # Empty text
    assert connector.validate({"text": "   "})["valid"] is False
    assert connector.validate({})["valid"] is False
    assert connector.validate(None)["valid"] is False  # type: ignore

    # Length boundary check (500 chars limit)
    assert connector.validate({"text": "a" * MASTODON_MAX_LENGTH})["valid"] is True
    exceeded = connector.validate({"text": "a" * (MASTODON_MAX_LENGTH + 1)})
    assert exceeded["valid"] is False
    assert "exceeds maximum allowed limit" in exceeded["error"]


# ==============================================================================
# 3. Publish, Status Retrieval, and Deletion Operations
# ==============================================================================


def test_publish_success():
    """Verify successful status publishing and extraction of real status ID and URL."""
    remote_status_id = "109353272494852934"
    remote_url = f"{TEST_BASE_URL}/@testuser/{remote_status_id}"
    created_at = "2026-10-17T09:15:00.000Z"

    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        assert request.method == "POST"
        assert request.url.path == "/api/v1/statuses"
        assert request.headers["Authorization"] == f"Bearer {TEST_TOKEN}"
        data = json.loads(request.content)
        assert data["status"] == "Hello, Fediverse!"
        return httpx.Response(
            200,
            json={
                "id": remote_status_id,
                "url": remote_url,
                "created_at": created_at,
                "visibility": "public",
            },
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )

    result = connector.publish({"text": "Hello, Fediverse!"})
    assert result["success"] is True
    assert result["id"] == remote_status_id
    assert result["url"] == remote_url
    assert result["destination"] == "mastodon"
    assert result["status"] == "published"
    assert result["created_at"] == created_at
    assert len(captured_requests) == 1


def test_publish_with_optional_fields_and_idempotency():
    """Verify optional fields (visibility, spoiler_text, language) and idempotency header are sent."""
    captured_payload = {}
    captured_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload, captured_headers
        captured_payload = json.loads(request.content)
        captured_headers = dict(request.headers)
        return httpx.Response(200, json={"id": "20001", "url": f"{TEST_BASE_URL}/@u/20001"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )

    content = {
        "text": "Sensitive announcement",
        "visibility": "unlisted",
        "spoiler_text": "Content Warning",
        "sensitive": True,
        "language": "en",
        "idempotency_key": "custom-idem-123",
    }
    result = connector.publish(content)
    assert result["success"] is True
    assert captured_payload["visibility"] == "unlisted"
    assert captured_payload["spoiler_text"] == "Content Warning"
    assert captured_payload["sensitive"] is True
    assert captured_payload["language"] == "en"
    assert captured_headers.get("idempotency-key") == "custom-idem-123"


def test_get_status_found():
    """Verify status retrieval succeeds when post exists on Mastodon."""
    status_id = "109353272494852934"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == f"/api/v1/statuses/{status_id}"
        return httpx.Response(
            200,
            json={
                "id": status_id,
                "url": f"{TEST_BASE_URL}/@user/{status_id}",
                "content": "<p>Hello world</p>",
                "created_at": "2026-10-17T09:00:00.000Z",
            },
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )

    result = connector.get_status(status_id)
    assert result["found"] is True
    assert result["id"] == status_id
    assert result["destination"] == "mastodon"
    assert result["content"] == "<p>Hello world</p>"


def test_get_status_not_found():
    """Verify status retrieval returns found: False on HTTP 404."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Record not found"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )

    result = connector.get_status("missing_999")
    assert result["found"] is False
    assert result["id"] == "missing_999"
    assert "not found" in result["error"].lower()


def test_delete_success():
    """Verify deletion returns success: True on HTTP 200."""
    status_id = "109353272494852934"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == f"/api/v1/statuses/{status_id}"
        return httpx.Response(200, json={"id": status_id, "text": "deleted"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )

    result = connector.delete(status_id)
    assert result["success"] is True
    assert result["id"] == status_id
    assert result["destination"] == "mastodon"


def test_delete_not_found():
    """Verify deletion returns success: False on HTTP 404."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Record not found"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )

    result = connector.delete("missing_999")
    assert result["success"] is False
    assert result["id"] == "missing_999"
    assert "not found" in result["error"].lower()


# ==============================================================================
# 4. Error Mapping & Downstream Failure Scenarios
# ==============================================================================


def test_auth_expired_401():
    """Verify HTTP 401 maps to AuthExpiredError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "The access token is invalid"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )

    with pytest.raises(AuthExpiredError) as exc:
        connector.publish({"text": "Test auth failure"})
    assert "authentication failed" in str(exc.value).lower()


def test_rate_limited_429_with_retry_after():
    """Verify HTTP 429 maps to RateLimitedError and includes Retry-After."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": "Throttled"},
            headers={"Retry-After": "45"},
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )

    with pytest.raises(RateLimitedError) as exc:
        connector.publish({"text": "Rate limited test"})
    assert "rate limit reached" in str(exc.value).lower()
    assert "45 seconds" in str(exc.value)


def test_forbidden_403_scope_error():
    """Verify HTTP 403 for permission / scope errors maps to ForbiddenError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": "This action is outside the authorized scopes"},
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )

    with pytest.raises(ForbiddenError) as exc:
        connector.publish({"text": "Forbidden action"})
    assert "forbidden" in str(exc.value).lower()
    assert exc.value.status_code == 403


def test_forbidden_403_moderation_content_rejected():
    """Verify HTTP 403 mentioning moderation or content maps to ContentRejectedError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": "Content was blocked by destination moderation rules"},
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )

    with pytest.raises(ContentRejectedError) as exc:
        connector.publish({"text": "Moderated post"})
    assert "rejected" in str(exc.value).lower()
    assert exc.value.status_code == 403


def test_network_timeout():
    """Verify timeout during request maps to NetworkError."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out")

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )

    with pytest.raises(NetworkError) as exc:
        connector.publish({"text": "Timeout test"})
    assert "timed out" in str(exc.value).lower()


def test_network_connection_error():
    """Verify network connection errors map to NetworkError."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )

    with pytest.raises(NetworkError) as exc:
        connector.publish({"text": "Connection failure test"})
    assert "network error" in str(exc.value).lower()


def test_malformed_json_response():
    """Verify non-JSON 200 response maps to DestinationError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>Internal gateway</html>")

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )

    with pytest.raises(DestinationError) as exc:
        connector.publish({"text": "Malformed response test"})
    assert "malformed" in str(exc.value).lower()


# ==============================================================================
# 5. Security & Credential Redaction Verification
# ==============================================================================


def test_credential_redaction_for_mastodon_tokens():
    """Verify access tokens and Authorization headers are redacted in structured logging."""
    sensitive_payload = {
        "connector_key": "mastodon",
        "access_token": "secret_mastodon_token_to_redact",
        "authorization": "Bearer secret_mastodon_token_to_redact",
        "headers": {
            "Authorization": "Bearer secret_mastodon_token_to_redact",
        },
        "content": {"text": "Publishing status"},
    }
    redacted = redact_sensitive_data(sensitive_payload)

    assert redacted["access_token"] == "[REDACTED]"
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["headers"]["Authorization"] == "[REDACTED]"
    assert "secret_mastodon_token_to_redact" not in str(redacted)


# ==============================================================================
# 6. Full API Router Integration with Mastodon Connector
# ==============================================================================


def test_api_publish_and_status_flow_with_mastodon():
    """Verify end-to-end publish and get_status via POST /connector/v1/mastodon/{method}."""
    post_id = "8899001122"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v1/statuses":
            return httpx.Response(
                200,
                json={
                    "id": post_id,
                    "url": f"{TEST_BASE_URL}/@bot/{post_id}",
                    "created_at": "2026-10-17T12:00:00.000Z",
                },
            )
        if request.method == "GET" and request.url.path == f"/api/v1/statuses/{post_id}":
            return httpx.Response(
                200,
                json={
                    "id": post_id,
                    "url": f"{TEST_BASE_URL}/@bot/{post_id}",
                    "content": "<p>E2E API post</p>",
                    "created_at": "2026-10-17T12:00:00.000Z",
                },
            )
        return httpx.Response(404)

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )
    register_connector("mastodon", connector)

    # 1. Publish via API
    pub_res = client.post(
        "/connector/v1/mastodon/publish",
        json={"text": "E2E API post to Mastodon"},
    )
    assert pub_res.status_code == 200
    pub_data = pub_res.json()
    assert pub_data["success"] is True
    assert pub_data["id"] == post_id
    assert pub_data["destination"] == "mastodon"

    # 2. Query status via API
    status_res = client.post(
        "/connector/v1/mastodon/get_status",
        json={"post_id": post_id},
    )
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["found"] is True
    assert status_data["id"] == post_id


def test_api_mastodon_idempotency_replay():
    """Verify Idempotency-Key support with Mastodon connector prevents duplicate posts."""
    post_id = "idem_mastodon_4455"
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "id": post_id,
                "url": f"{TEST_BASE_URL}/@bot/{post_id}",
                "created_at": "2026-10-17T12:00:00.000Z",
            },
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )
    register_connector("mastodon", connector)

    headers = {"Idempotency-Key": "mastodon-idem-test-key-1"}
    payload = {"text": "Publish with idempotency"}

    # First request
    r1 = client.post("/connector/v1/mastodon/publish", headers=headers, json=payload)
    assert r1.status_code == 200
    assert r1.json()["id"] == post_id
    assert call_count == 1

    # Second request with identical key and payload
    r2 = client.post("/connector/v1/mastodon/publish", headers=headers, json=payload)
    assert r2.status_code == 200
    assert r2.json()["id"] == post_id
    # Ensure downstream Mastodon API was NOT called a second time
    assert call_count == 1


def test_api_mastodon_background_job_execution():
    """Verify asynchronous background processing works seamlessly with Mastodon connector."""
    post_id = "async_mastodon_9988"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": post_id,
                "url": f"{TEST_BASE_URL}/@bot/{post_id}",
                "created_at": "2026-10-17T12:00:00.000Z",
            },
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = MastodonConnector(
        base_url=TEST_BASE_URL,
        access_token=TEST_TOKEN,
        http_client=mock_client,
    )
    register_connector("mastodon", connector)

    # Trigger background execution via ?async=true
    resp = client.post(
        "/connector/v1/mastodon/publish?async=true",
        json={"text": "Background status update to Mastodon"},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # Verify background execution succeeded and result holds Mastodon post metadata
    status_resp = client.get(f"/connector/v1/jobs/{job_id}")
    assert status_resp.status_code == 200
    job_data = status_resp.json()
    assert job_data["status"] == "succeeded"
    assert job_data["result"]["id"] == post_id
    assert job_data["result"]["destination"] == "mastodon"
    assert job_data["result"]["url"] == f"{TEST_BASE_URL}/@bot/{post_id}"
