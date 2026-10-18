"""Unit tests for the connector interface and MockConnector implementation."""

import pytest
from app.connectors.base import BaseConnector
from app.connectors.mock import MockConnector


@pytest.fixture
def connector() -> MockConnector:
    """Fixture providing a fresh instance of MockConnector for each test."""
    return MockConnector()


def test_mock_connector_inherits_base_connector():
    """Verify MockConnector is an instance of BaseConnector."""
    connector = MockConnector()
    assert isinstance(connector, BaseConnector)


def test_validate_valid_content(connector: MockConnector):
    """Verify validation passes for valid content containing non-empty text."""
    valid_payload = {"text": "Hello, Incubrix Distribution Network!"}
    result = connector.validate(valid_payload)
    assert result["valid"] is True

    # Also check with additional metadata fields
    rich_payload = {
        "text": "Post with tags and author",
        "tags": ["tech", "cloud"],
        "author": "engineer",
    }
    result_rich = connector.validate(rich_payload)
    assert result_rich["valid"] is True


def test_validate_invalid_content(connector: MockConnector):
    """Verify validation fails appropriately for various invalid payloads."""
    # Missing 'text' key
    res_empty_dict = connector.validate({})
    assert res_empty_dict["valid"] is False
    assert "error" in res_empty_dict

    # Empty string text
    res_empty_str = connector.validate({"text": ""})
    assert res_empty_str["valid"] is False
    assert "error" in res_empty_str

    # Whitespace-only text
    res_whitespace = connector.validate({"text": "    \t\n  "})
    assert res_whitespace["valid"] is False
    assert "error" in res_whitespace

    # Non-string text
    res_int_text = connector.validate({"text": 12345})
    assert res_int_text["valid"] is False
    assert "error" in res_int_text

    # Non-dictionary input
    res_none = connector.validate(None)  # type: ignore[arg-type]
    assert res_none["valid"] is False
    assert "error" in res_none


def test_publish_valid_content(connector: MockConnector):
    """Verify publishing valid content succeeds with generated post ID and mock destination."""
    payload = {"text": "Publishing test article"}
    result = connector.publish(payload)

    assert result["success"] is True
    assert "id" in result
    assert result["id"].startswith("mock_")
    assert result["status"] == "published"
    assert result["destination"] == "mock"
    assert "created_at" in result


def test_publish_invalid_content_fails(connector: MockConnector):
    """Verify publish rejects invalid payloads and does not store anything."""
    result = connector.publish({"text": "   "})

    assert result["success"] is False
    assert "error" in result


def test_get_status_existing_post(connector: MockConnector):
    """Verify get_status retrieves full details for a previously published post."""
    payload = {"text": "Status test post"}
    publish_result = connector.publish(payload)
    post_id = publish_result["id"]

    status_result = connector.get_status(post_id)
    assert status_result["found"] is True
    assert status_result["id"] == post_id
    assert status_result["status"] == "published"
    assert status_result["destination"] == "mock"
    assert status_result["content"]["text"] == "Status test post"
    assert "created_at" in status_result


def test_get_status_nonexistent_post(connector: MockConnector):
    """Verify get_status returns not-found payload for unknown post ID."""
    result = connector.get_status("mock_nonexistent_999")
    assert result["found"] is False
    assert "error" in result
    assert "mock_nonexistent_999" in result["error"]


def test_delete_existing_post(connector: MockConnector):
    """Verify delete removes an existing post and subsequent queries report not found."""
    payload = {"text": "Post to be deleted"}
    publish_result = connector.publish(payload)
    post_id = publish_result["id"]

    # Delete the post
    delete_result = connector.delete(post_id)
    assert delete_result["success"] is True
    assert delete_result["id"] == post_id

    # Verify post is no longer found
    status_result = connector.get_status(post_id)
    assert status_result["found"] is False


def test_delete_nonexistent_post(connector: MockConnector):
    """Verify delete returns appropriate failure response for unknown post ID."""
    result = connector.delete("mock_missing_post_404")
    assert result["success"] is False
    assert "error" in result
    assert "mock_missing_post_404" in result["error"]
