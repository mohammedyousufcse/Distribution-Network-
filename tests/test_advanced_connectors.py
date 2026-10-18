"""Unit and contract tests for Advanced Connectors: Hashnode and Slack."""

import asyncio
import pytest
from app.api.connector import _invoke_connector
from app.connectors.hashnode import HashnodeConnector
from app.connectors.registry import get_connector
from app.connectors.slack import SlackConnector
from app.models.payloads import ContentPayload


def test_hashnode_manifest_and_validation():
    connector = get_connector("hashnode")
    assert isinstance(connector, HashnodeConnector)
    manifest = connector.get_manifest()
    assert manifest["key"] == "hashnode"
    assert manifest["capabilities"]["publish"] is True

    # Validation
    p_empty = ContentPayload(text="")
    assert connector.validate(p_empty).valid is False

    p_valid = ContentPayload(title="GraphQL Microservices", text="Detailed markdown body.")
    assert connector.validate(p_valid).valid is True


def test_hashnode_simulation_lifecycle():
    connector = HashnodeConnector()
    dest = {"publication_id": "pub_123", "simulation": True}
    conn = {"simulation": True}
    payload = ContentPayload(title="Hashnode Article", text="Tech article text.")

    pub = asyncio.run(_invoke_connector(connector, "publish", content=payload, destination=dest, connection=conn, idempotency_key="hn_1"))
    assert pub["status"] == "published"
    assert pub["platform_post_id"].startswith("sim_hashnode_")

    status = asyncio.run(_invoke_connector(connector, "get_status", platform_post_id=pub["platform_post_id"], destination=dest, connection=conn))
    assert status["status"] == "published"

    deleted = asyncio.run(_invoke_connector(connector, "delete", platform_post_id=pub["platform_post_id"], destination=dest, connection=conn))
    assert deleted["deleted"] is True

    metrics = asyncio.run(_invoke_connector(connector, "fetch_metrics", platform_post_id=pub["platform_post_id"], destination=dest, connection=conn))
    assert "views" in metrics
    assert "clicks" in metrics


def test_slack_manifest_and_lifecycle():
    connector = get_connector("slack")
    assert isinstance(connector, SlackConnector)
    manifest = connector.get_manifest()
    assert manifest["key"] == "slack"
    assert "channel_post" in manifest["surfaces"]

    dest = {"webhook_url": "https://hooks.slack.com/services/T00/B00/X00", "simulation": True}
    conn = {"simulation": True}
    payload = ContentPayload(title="Release Announcement", text="Deployment complete.")

    pub = asyncio.run(_invoke_connector(connector, "publish", content=payload, destination=dest, connection=conn, idempotency_key="slk_1"))
    assert pub["status"] == "published"
    assert pub["platform_post_id"].startswith("sim_slack_")

    deleted = asyncio.run(_invoke_connector(connector, "delete", platform_post_id=pub["platform_post_id"], destination=dest, connection=conn))
    assert deleted["deleted"] is True
