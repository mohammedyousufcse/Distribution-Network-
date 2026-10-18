"""Unit and contract tests for Mailchimp / Kit Newsletter Connector."""

import pytest
from app.connectors.mailchimp import MailchimpConnector
from app.connectors.registry import get_connector
from app.models.errors import ConnectorException
from app.models.payloads import ContentPayload


def test_mailchimp_registered():
    connector = get_connector("mailchimp")
    assert connector is not None
    assert isinstance(connector, MailchimpConnector)
    assert connector.name == "mailchimp"


def test_mailchimp_manifest():
    connector = MailchimpConnector()
    manifest = connector.get_manifest()
    assert manifest["key"] == "mailchimp"
    assert manifest["capabilities"]["publish"] is True
    assert manifest["capabilities"]["fetch_metrics"] is True
    assert "campaign" in manifest["surfaces"]


def test_mailchimp_validation_empty_body():
    connector = MailchimpConnector()
    payload = ContentPayload(title="Test Newsletter", text="")
    val = connector.validate(payload)
    assert val.valid is False
    assert any("empty" in v.lower() for v in val.violations)


def test_mailchimp_publish_simulation():
    connector = MailchimpConnector()
    payload = ContentPayload(
        title="Weekly Developer Dispatch #42",
        text="Welcome to this week's issue on microservices and long-tail distribution.",
        simulation=True,
    )
    result = connector.publish(payload)
    assert result.platform_post_id.startswith("sim_mc_")
    assert "mailchi.mp" in result.live_url
    assert result.status == "sent"
    assert result.metadata["simulation"] is True


def test_mailchimp_status_and_delete_simulation():
    connector = MailchimpConnector()
    sim_id = "sim_mc_98765432"
    status_res = connector.get_status(sim_id)
    assert status_res["status"] == "sent"
    assert status_res["platform_post_id"] == sim_id

    del_res = connector.delete(sim_id)
    assert del_res["deleted"] is True


def test_mailchimp_fetch_metrics():
    connector = MailchimpConnector()
    metrics = connector.fetch_metrics("sim_mc_12345")
    assert metrics["views"] > 0
    assert metrics["clicks"] > 0
    assert "shares" in metrics


def test_mailchimp_real_missing_auth():
    connector = MailchimpConnector()
    payload = ContentPayload(
        title="Production Broadcast",
        text="Live announcement content without simulation flag.",
        simulation=False,
    )
    with pytest.raises(ConnectorException) as exc:
        connector.publish(payload, connection={})
    assert exc.value.error_code == "CONNECTION_AUTH_EXPIRED"
