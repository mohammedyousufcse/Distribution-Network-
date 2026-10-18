"""Unit tests for AI rules capture and human confirmation workflow."""

import pytest
from app.services.rules_capture_service import RulesCaptureService


def test_propose_rules_extraction():
    guidelines_text = """
    Welcome to our community!
    1. No self-promotion or advertising allowed in main threads.
    2. External links are forbidden; please use text-only format.
    3. Limit of 2 posts per week per user.
    4. Any AI-generated content or LLM text must be disclosed.
    5. Title under 80 characters.
    """
    proposal = RulesCaptureService.propose_rules(
        community_name="Strict Tech Forum",
        rules_text=guidelines_text,
        rules_url="https://forum.example.com/rules",
    )

    assert proposal["proposal_id"].startswith("rule_prop_")
    assert proposal["status"] == "pending_human_confirmation"
    assert proposal["confidence_score"] >= 0.80

    rules = proposal["proposed_rules"]
    assert rules["allow_self_promotion"] is False
    assert rules["allow_links"] is False
    assert rules["weekly_limit"] == 2
    assert rules["require_ai_disclosure"] is True
    assert rules["title_max_chars"] == 80


def test_confirm_rules_workflow():
    sample_text = "Friendly developer chat. 1 post per day allowed. No spam."
    proposal = RulesCaptureService.propose_rules("Dev Chat", sample_text)
    pid = proposal["proposal_id"]

    # Human confirms with custom override
    confirmed = RulesCaptureService.confirm_rules(
        proposal_id=pid,
        confirmed_by="alex_moderator",
        overrides={"weekly_limit": 4},
    )

    assert confirmed["status"] == "confirmed"
    assert confirmed["confirmed_by"] == "alex_moderator"
    assert confirmed["active_rules"]["weekly_limit"] == 4

    # Verify retrieved proposal matches
    retrieved = RulesCaptureService.get_proposal(pid)
    assert retrieved is not None
    assert retrieved["status"] == "confirmed"
    assert retrieved["active_rules"]["weekly_limit"] == 4
