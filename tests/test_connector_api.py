"""Integration tests for the connector REST API endpoints."""

import pytest
from fastapi.testclient import TestClient
from app.connectors.mock import MockConnector
from app.connectors.registry import get_connector
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_mock_state() -> None:
    """Ensure in-memory mock store and policy limits are clean before each test."""
    from app.services.policy_service import get_policy_service

    connector = get_connector("mock")
    if isinstance(connector, MockConnector):
        connector.clear()
    get_policy_service().reset()



def test_validate_valid_content():
    """Verify POST /connector/v1/mock/validate returns valid=True for non-empty text."""
    response = client.post(
        "/connector/v1/mock/validate",
        json={"content": {"text": "Valid test post content."}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True


def test_validate_invalid_content():
    """Verify POST /connector/v1/mock/validate returns valid=False for empty text."""
    response = client.post(
        "/connector/v1/mock/validate",
        json={"content": {"text": "   "}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert "error" in data


def test_publish_valid_content():
    """Verify POST /connector/v1/mock/publish generates post ID and stores locally."""
    payload = {"content": {"text": "Launching new feature announcement."}}
    response = client.post("/connector/v1/mock/publish", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "id" in data
    assert data["id"].startswith("mock_")
    assert data["status"] == "published"
    assert data["destination"] == "mock"
    assert "created_at" in data


def test_publish_invalid_content():
    """Verify POST /connector/v1/mock/publish returns HTTP 400 when text is empty."""
    response = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": ""}},
    )
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "non-empty 'text'" in data["detail"]


def test_publish_missing_content():
    """Verify POST /connector/v1/mock/publish returns HTTP 400 when content is missing."""
    response = client.post("/connector/v1/mock/publish", json={})
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "content" in data["detail"]


def test_get_status_existing_post():
    """Verify POST /connector/v1/mock/get_status returns post details for a valid post ID."""
    # First publish a post
    publish_res = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Status lookup target"}},
    )
    assert publish_res.status_code == 200
    post_id = publish_res.json()["id"]

    # Check status
    status_res = client.post(
        "/connector/v1/mock/get_status",
        json={"post_id": post_id},
    )
    assert status_res.status_code == 200
    data = status_res.json()
    assert data["found"] is True
    assert data["id"] == post_id
    assert data["status"] == "published"
    assert data["destination"] == "mock"
    assert data["content"]["text"] == "Status lookup target"


def test_get_status_missing_post_id():
    """Verify POST /connector/v1/mock/get_status returns HTTP 400 when post_id is missing."""
    response = client.post("/connector/v1/mock/get_status", json={})
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "post_id" in data["detail"]


def test_get_status_nonexistent_post():
    """Verify POST /connector/v1/mock/get_status returns HTTP 404 for unknown post ID."""
    response = client.post(
        "/connector/v1/mock/get_status",
        json={"post_id": "mock_nonexistent_000"},
    )
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "mock_nonexistent_000" in data["detail"]


def test_delete_existing_post():
    """Verify POST /connector/v1/mock/delete removes post and subsequent lookups return 404."""
    # First publish
    publish_res = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Post to be deleted via API"}},
    )
    post_id = publish_res.json()["id"]

    # Delete
    delete_res = client.post(
        "/connector/v1/mock/delete",
        json={"post_id": post_id},
    )
    assert delete_res.status_code == 200
    data = delete_res.json()
    assert data["success"] is True
    assert data["id"] == post_id

    # Confirm post is gone
    status_res = client.post(
        "/connector/v1/mock/get_status",
        json={"post_id": post_id},
    )
    assert status_res.status_code == 404


def test_delete_missing_post_id():
    """Verify POST /connector/v1/mock/delete returns HTTP 400 when post_id is omitted."""
    response = client.post("/connector/v1/mock/delete", json={})
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "post_id" in data["detail"]


def test_delete_nonexistent_post():
    """Verify POST /connector/v1/mock/delete returns HTTP 404 for unknown post ID."""
    response = client.post(
        "/connector/v1/mock/delete",
        json={"post_id": "mock_missing_post_888"},
    )
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "mock_missing_post_888" in data["detail"]


def test_unknown_connector_key():
    """Verify unknown connector key returns HTTP 404 with list of available connectors."""
    response = client.post(
        "/connector/v1/unregistered_destination/publish",
        json={"content": {"text": "Sample"}},
    )
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "unregistered_destination" in data["detail"]
    assert "mock" in data["detail"]


def test_invalid_method():
    """Verify unsupported method returns HTTP 400 with list of supported methods."""
    response = client.post(
        "/connector/v1/mock/unsupported_method",
        json={"content": {"text": "Sample"}},
    )
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "unsupported_method" in data["detail"]
    assert "publish" in data["detail"]


def test_publish_direct_top_level_payload():
    """Verify top-level payload with 'text' is accepted gracefully."""
    response = client.post(
        "/connector/v1/mock/publish",
        json={"text": "Direct payload without content wrapper."},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "id" in data
