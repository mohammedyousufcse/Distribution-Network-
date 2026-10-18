"""
Unit and contract tests for the Six Core Connectors:
1. Discourse
2. Lemmy
3. Dev.to
4. Ghost
5. Generic HMAC-signed Webhook
6. Assisted Manual-Post Connector
"""

import asyncio
import time
import pytest
import httpx
from fastapi.testclient import TestClient

from app.api.connector import _invoke_connector
from app.connectors.assisted import AssistedConnector
from app.connectors.devto import DevtoConnector
from app.connectors.discourse import DiscourseConnector
from app.connectors.ghost import GhostConnector, _generate_ghost_jwt
from app.connectors.lemmy import LemmyConnector
from app.connectors.webhook import (
    WebhookConnector,
    generate_webhook_signature,
    verify_webhook_signature,
)
from app.main import app
from app.models.errors import ConnectorException
from app.models.payloads import ContentPayload

client = TestClient(app)


# -------------------------------------------------------------------------
# 1. DISCOURSE CONNECTOR TESTS
# -------------------------------------------------------------------------

def test_discourse_manifest():
    connector = DiscourseConnector()
    manifest = connector.get_manifest()
    assert manifest["key"] == "discourse"
    assert "topic" in manifest["surfaces"]
    assert manifest["capabilities"]["publish"] is True
    assert manifest["capabilities"]["get_status"] is True
    assert manifest["capabilities"]["delete"] is True


def test_discourse_validation():
    connector = DiscourseConnector()
    p_invalid = ContentPayload(title="", text="")
    val = connector.validate(p_invalid)
    assert val.valid is False
    assert len(val.violations) > 0

    p_valid = ContentPayload(title="Valid Topic Title", text="This is a valid body of text for Discourse.")
    val2 = connector.validate(p_valid)
    assert val2.valid is True
    assert val2.ok is True


def test_discourse_simulation_publish_status_delete():
    connector = DiscourseConnector()
    dest = {"base_url": "https://meta.discourse.org", "category_id": 1, "simulation": True}
    conn = {"api_key": "dummy", "api_username": "system", "simulation": True}

    payload = ContentPayload(title="Simulated Discourse Topic", text="Discussion body for testing.")
    pub = asyncio.run(_invoke_connector(connector, "publish", content=payload, destination=dest, connection=conn, idempotency_key="disc_123"))
    assert pub["id"].startswith("disc_") or pub["platform_post_id"].startswith("disc_") or "id" in pub
    assert pub["status"] == "published"

    pid = pub.get("platform_post_id") or pub["id"]
    status = asyncio.run(_invoke_connector(connector, "get_status", platform_post_id=pid, destination=dest, connection=conn))
    assert status["status"] == "published"

    delete_res = asyncio.run(_invoke_connector(connector, "delete", platform_post_id=pid, destination=dest, connection=conn))
    assert delete_res["deleted"] is True or delete_res["success"] is True


# -------------------------------------------------------------------------
# 2. LEMMY CONNECTOR TESTS
# -------------------------------------------------------------------------

def test_lemmy_manifest():
    connector = LemmyConnector()
    manifest = connector.get_manifest()
    assert manifest["key"] == "lemmy"
    assert "community_post" in manifest["surfaces"]
    assert manifest["capabilities"]["publish"] is True
    assert manifest["capabilities"]["fetch_metrics"] is True


def test_lemmy_validation():
    connector = LemmyConnector()
    p_long = ContentPayload(title="A" * 201, text="Body")
    val = connector.validate(p_long)
    assert val.valid is False

    p_valid = ContentPayload(title="Valid Lemmy Post", text="Lemmy post body content.")
    val_valid = connector.validate(p_valid)
    assert val_valid.valid is True


def test_lemmy_simulation_lifecycle():
    connector = LemmyConnector()
    dest = {"instance_url": "https://lemmy.world", "community_id": 12, "simulation": True}
    conn = {"auth_token": "lemmy_jwt_token", "simulation": True}

    payload = ContentPayload(title="Lemmy Tech Post", text="Content for Lemmy post.")
    pub = asyncio.run(_invoke_connector(connector, "publish", content=payload, destination=dest, connection=conn, idempotency_key="lemmy_001"))
    assert pub["status"] == "published"

    pid = pub.get("platform_post_id") or pub["id"]
    status = asyncio.run(_invoke_connector(connector, "get_status", platform_post_id=pid, destination=dest, connection=conn))
    assert status["status"] == "published"

    deleted = asyncio.run(_invoke_connector(connector, "delete", platform_post_id=pid, destination=dest, connection=conn))
    assert deleted["deleted"] is True or deleted["success"] is True


# -------------------------------------------------------------------------
# 3. DEV.TO CONNECTOR TESTS
# -------------------------------------------------------------------------

def test_devto_manifest():
    connector = DevtoConnector()
    manifest = connector.get_manifest()
    assert manifest["key"] == "devto"
    assert manifest["auth"]["header"] == "api-key"
    assert manifest["specification_limits"]["max_tags"] == 4


def test_devto_validation():
    connector = DevtoConnector()
    p_tags = ContentPayload(title="Dev Title", text="Body text", metadata={"tags": ["a", "b", "c", "d", "e"]})
    val = connector.validate(p_tags)
    assert val.valid is False
    assert "maximum of 4 tags" in val.violations[0]

    p_ok = ContentPayload(title="Dev Title", text="Body text", metadata={"tags": ["python", "fastapi"]})
    assert connector.validate(p_ok).valid is True


def test_devto_simulation_lifecycle():
    connector = DevtoConnector()
    dest = {"base_url": "https://dev.to/api", "simulation": True}
    conn = {"api_key": "test_api_key", "simulation": True}

    payload = ContentPayload(title="Python Best Practices", text="Body about python.")
    pub = asyncio.run(_invoke_connector(connector, "publish", content=payload, destination=dest, connection=conn, idempotency_key="devto_42"))
    assert pub["platform_post_id"].startswith("sim_devto_")
    assert pub["status"] == "published"

    pid = pub["platform_post_id"]
    status = asyncio.run(_invoke_connector(connector, "get_status", platform_post_id=pid, destination=dest, connection=conn))
    assert status["status"] == "published"

    metrics = asyncio.run(_invoke_connector(connector, "fetch_metrics", platform_post_id=pid, destination=dest, connection=conn))
    assert "views" in metrics

    deleted = asyncio.run(_invoke_connector(connector, "delete", platform_post_id=pid, destination=dest, connection=conn))
    assert deleted["deleted"] is True


# -------------------------------------------------------------------------
# 4. GHOST CONNECTOR TESTS
# -------------------------------------------------------------------------

def test_ghost_manifest_and_jwt():
    connector = GhostConnector()
    manifest = connector.get_manifest()
    assert manifest["key"] == "ghost"
    assert manifest["auth"]["format"] == "id:secret"

    key_id = "6510abcd1234ef0123456789"
    secret_hex = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    token = _generate_ghost_jwt(f"{key_id}:{secret_hex}")
    parts = token.split(".")
    assert len(parts) == 3


def test_ghost_simulation_lifecycle():
    connector = GhostConnector()
    dest = {"base_url": "http://ghost:2368", "simulation": True}
    conn = {"admin_api_key": "id:secret", "simulation": True}

    payload = ContentPayload(title="Ghost Tech Article", text="Hello from Ghost test.")
    pub = asyncio.run(_invoke_connector(connector, "publish", content=payload, destination=dest, connection=conn, idempotency_key="ghost_99"))
    assert pub["platform_post_id"].startswith("sim_ghost_")
    assert pub["status"] == "published"

    pid = pub["platform_post_id"]
    status = asyncio.run(_invoke_connector(connector, "get_status", platform_post_id=pid, destination=dest, connection=conn))
    assert status["status"] == "published"

    deleted = asyncio.run(_invoke_connector(connector, "delete", platform_post_id=pid, destination=dest, connection=conn))
    assert deleted["deleted"] is True


# -------------------------------------------------------------------------
# 5. GENERIC HMAC WEBHOOK CONNECTOR TESTS
# -------------------------------------------------------------------------

def test_webhook_manifest():
    connector = WebhookConnector()
    manifest = connector.get_manifest()
    assert manifest["key"] == "webhook"
    assert manifest["auth"]["type"] == "hmac_sha256"
    assert manifest["auth"]["header"] == "X-Hub-Signature-256"


def test_webhook_signature_and_replay_protection():
    secret = "super_secret_webhook_key_123"
    payload_bytes = b'{"event":"test","text":"hello"}'
    now = int(time.time())

    # Valid signature
    sig = generate_webhook_signature(payload_bytes, secret, now)
    assert sig.startswith("sha256=")
    valid, reason = verify_webhook_signature(payload_bytes, secret, sig, now, tolerance_seconds=300)
    assert valid is True
    assert reason == "Valid"

    # Tampered payload fails
    tampered_bytes = b'{"event":"test","text":"hacked"}'
    valid, reason = verify_webhook_signature(tampered_bytes, secret, sig, now, tolerance_seconds=300)
    assert valid is False
    assert "mismatch" in reason

    # Expired timestamp outside 300s window fails (replay attack prevention)
    expired_timestamp = now - 350
    sig_old = generate_webhook_signature(payload_bytes, secret, expired_timestamp)
    valid, reason = verify_webhook_signature(payload_bytes, secret, sig_old, expired_timestamp, tolerance_seconds=300)
    assert valid is False
    assert "outside tolerance window" in reason


def test_webhook_simulation_lifecycle():
    connector = WebhookConnector()
    dest = {"webhook_url": "https://partner.local/webhook", "simulation": True}
    conn = {"secret": "secret_abc", "simulation": True}

    payload = ContentPayload(title="Syndicated News", text="Body of syndicated story.")
    pub = asyncio.run(_invoke_connector(connector, "publish", content=payload, destination=dest, connection=conn, idempotency_key="wh_001"))
    assert pub["platform_post_id"].startswith("sim_webhook_")
    assert pub["status"] == "delivered"

    pid = pub["platform_post_id"]
    status = asyncio.run(_invoke_connector(connector, "get_status", platform_post_id=pid, destination=dest, connection=conn))
    assert status["status"] == "delivered"

    deleted = asyncio.run(_invoke_connector(connector, "delete", platform_post_id=pid, destination=dest, connection=conn))
    assert deleted["deleted"] is True


# -------------------------------------------------------------------------
# 6. ASSISTED CONNECTOR TESTS
# -------------------------------------------------------------------------

def test_assisted_manifest():
    connector = AssistedConnector()
    manifest = connector.get_manifest()
    assert manifest["key"] == "assisted"
    assert manifest["capabilities"]["build_assist_pack"] is True
    assert manifest["auth"]["type"] == "none"


def test_assisted_build_pack_structure():
    connector = AssistedConnector()
    dest = {
        "id": "hn_manual",
        "name": "Hacker News",
        "submission_url": "https://news.ycombinator.com/submit",
    }
    payload = ContentPayload(
        title="Show HN: My Cool Project",
        text="A brief explanation with a link.",
        media_urls=["https://example.com/screenshot.png"],
        metadata={"contains_ai": True},
    )

    pack = connector.build_assist_pack(payload, dest)
    assert pack["destination_id"] == "hn_manual"
    assert pack["deep_link"] == "https://news.ycombinator.com/submit"
    assert pack["status"] == "human_action_required"
    assert len(pack["files"]) == 1
    assert any("AI-assistance" in item for item in pack["checklist"])


def test_assisted_publish_returns_human_action_required():
    connector = AssistedConnector()
    dest = {
        "id": "reddit_manual",
        "name": "r/programming",
        "submission_url": "https://reddit.com/r/programming/submit",
    }
    conn = {}
    payload = ContentPayload(text="Manual posting content for reddit.")

    pub = asyncio.run(_invoke_connector(connector, "publish", content=payload, destination=dest, connection=conn, idempotency_key="assist_10"))
    assert pub["status"] == "human_action_required"
    assert pub["platform_post_id"].startswith("pack_")
    assert pub["metadata"]["assisted"] is True
    assert "assist_pack" in pub["metadata"]


# -------------------------------------------------------------------------
# 7. ROUTE INTEGRATION FOR CORE CONNECTORS
# -------------------------------------------------------------------------

def test_api_manifest_endpoint():
    for key in ("discourse", "lemmy", "devto", "ghost", "webhook", "assisted", "mock", "mastodon"):
        resp = client.get(f"/connector/v1/{key}/manifest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == key
        assert "capabilities" in data


def test_api_assisted_build_assist_pack():
    resp = client.post(
        "/connector/v1/assisted/build_assist_pack",
        json={
            "content": {"text": "Operator text to post manually", "title": "Checklist Post"},
            "destination": {"name": "Manual Forum", "submission_url": "https://example.com/submit"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "human_action_required"
    assert "checklist" in data
    assert data["deep_link"] == "https://example.com/submit"
