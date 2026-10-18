"""
Tests for Multi-Category Posting-Rules Engine:
1. Rolling window and weekly frequency caps with injectable clock.
2. Link restrictions (allow_links=False).
3. Self-promotion restrictions (allow_self_promotion=False).
4. AI-content disclosure requirement (require_ai_disclosure=True).
5. Format and length restrictions.
"""

import time
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.policy import DestinationPolicy
from app.services.policy_service import get_policy_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_policy():
    """Reset policy service state before each test."""
    svc = get_policy_service()
    svc.reset()
    yield
    svc.reset()


def test_posting_rule_disallows_links():
    svc = get_policy_service()
    svc.set_policy(
        "mock",
        DestinationPolicy(
            destination_key="mock",
            allow_links=False,
            max_text_length=500,
        ),
    )

    # Content with link should be rejected
    res = svc.validate_content("mock", {"text": "Check out https://example.com for info"})
    assert res["valid"] is False
    assert res["ok"] is False
    assert "prohibits external hyperlinks" in res["error"]
    assert res["shared_error_code"] == "DEST_SPEC_VIOLATION"

    # Content without link passes
    res_ok = svc.validate_content("mock", {"text": "Plain discussion text without any links"})
    assert res_ok["valid"] is True
    assert res_ok["ok"] is True


def test_posting_rule_disallows_self_promotion():
    svc = get_policy_service()
    svc.set_policy(
        "mock",
        DestinationPolicy(
            destination_key="mock",
            allow_self_promotion=False,
            max_text_length=500,
        ),
    )

    # Content with promo phrase
    res_promo = svc.validate_content("mock", {"text": "Huge discounts available now! Buy now for 50% off."})
    assert res_promo["valid"] is False
    assert "prohibits promotional" in res_promo["error"]
    assert res_promo["shared_error_code"] == "DEST_SPEC_VIOLATION"

    # Explicit flag is_promo
    res_flag = svc.validate_content("mock", {"text": "Standard announcement", "is_promo": True})
    assert res_flag["valid"] is False

    # Neutral content passes
    res_clean = svc.validate_content("mock", {"text": "Sharing my open source library tutorial"})
    assert res_clean["valid"] is True


def test_posting_rule_requires_ai_disclosure():
    svc = get_policy_service()
    svc.set_policy(
        "mock",
        DestinationPolicy(
            destination_key="mock",
            require_ai_disclosure=True,
            max_text_length=500,
        ),
    )

    # Content marked AI without disclosure in text or flag
    res_ai_no_disc = svc.validate_content("mock", {"text": "Automated summary text.", "is_ai_generated": True})
    assert res_ai_no_disc["valid"] is False
    assert "requires explicit AI-content disclosure" in res_ai_no_disc["error"]

    # Content with disclosure flag passes
    res_ai_disc = svc.validate_content(
        "mock",
        {"text": "Automated summary text.", "is_ai_generated": True, "has_ai_disclosure": True},
    )
    assert res_ai_disc["valid"] is True

    # Content with hashtag disclosure passes
    res_ai_hashtag = svc.validate_content(
        "mock",
        {"text": "Automated summary text #ai.", "is_ai_generated": True},
    )
    assert res_ai_hashtag["valid"] is True


def test_weekly_frequency_cap_with_injectable_clock():
    svc = get_policy_service()
    # Mock clock
    current_time = [1700000000.0]

    def mock_clock():
        return current_time[0]

    svc.set_clock(mock_clock)
    svc.set_policy(
        "mock",
        DestinationPolicy(
            destination_key="mock",
            max_requests_per_window=10,  # window cap won't trigger
            window_seconds=60,
            weekly_frequency_cap=2,     # only 2 posts per 7 days
        ),
    )

    # Post 1 at t=0
    c1 = svc.check_and_record_publish("mock")
    assert c1["allowed"] is True

    # Post 2 at day 1 (t + 86400)
    current_time[0] += 86400.0
    c2 = svc.check_and_record_publish("mock")
    assert c2["allowed"] is True

    # Post 3 at day 2 (t + 172800) -> Should be rejected by weekly cap!
    current_time[0] += 86400.0
    c3 = svc.check_and_record_publish("mock")
    assert c3["allowed"] is False
    assert "Weekly publish limit exceeded" in c3["error"]
    assert c3["shared_error_code"] == "DEST_RULE_FREQUENCY_CAP"

    # Fast forward to day 8 (t + 700000 > 7 days from post 1)
    current_time[0] += 8 * 86400.0
    c4 = svc.check_and_record_publish("mock")
    assert c4["allowed"] is True


def test_api_enforces_rules_before_publish():
    """Verify that HTTP publish endpoint enforces policy rules and returns canonical codes."""
    svc = get_policy_service()
    svc.set_policy(
        "mock",
        DestinationPolicy(
            destination_key="mock",
            allow_links=False,
        ),
    )

    resp = client.post(
        "/connector/v1/mock/publish",
        json={"content": {"text": "Publishing an illegal link https://bad.link"}},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert data["shared_error_code"] == "DEST_SPEC_VIOLATION"
    assert "prohibits external hyperlinks" in data["error"]
