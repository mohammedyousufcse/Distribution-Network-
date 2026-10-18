"""Unit tests for content tailoring engine and audience relevance scoring."""

import pytest
from app.services.tailoring_service import tailoring_service, truncate_at_word_boundary


def test_truncate_at_word_boundary():
    sample = "The quick brown fox jumps over the lazy dog"
    truncated = truncate_at_word_boundary(sample, 25)
    assert truncated == "The quick brown fox..."
    assert len(truncated) <= 25


def test_forum_discussion_tailoring():
    dest = {"id": "discourse_forum", "connector_key": "discourse", "surface": "topic"}
    content = {"title": "New Gateway Release", "text": "We just deployed the new distribution network."}

    tailored = tailoring_service.tailor_content(content, dest)
    assert tailored["title"] == "New Gateway Release"
    assert "What are your thoughts on this?" in tailored["text"]
    assert len(tailored["tailoring_applied"]) > 0


def test_article_canonical_tailoring():
    dest = {"id": "devto_engineering", "connector_key": "devto", "surface": "article"}
    content = {
        "title": "Scaling Distributed Microservices",
        "text": "Detailed technical analysis of retry architectures.",
        "canonical_url": "https://incubrix.com/blog/scaling",
        "tags": ["Python!", "#FastAPI", "Docker"],
    }

    tailored = tailoring_service.tailor_content(content, dest)
    assert "Originally published at [https://incubrix.com/blog/scaling]" in tailored["text"]
    assert tailored["tags"] == ["python", "fastapi", "docker"]


def test_audience_relevance_scoring():
    high_match = {
        "id": "ai_founder_hub",
        "name": "AI SaaS Founders Community",
        "audience": "Founders building artificial intelligence and machine learning software",
        "audience_tags": ["ai", "saas", "founders", "creators"],
    }
    score_high = tailoring_service.score_relevance(high_match)
    assert score_high["relevance_score"] >= 4
    assert "ai" in score_high["matched_pillars"]

    low_match = {
        "id": "gardening_club",
        "name": "Organic Gardening Enthusiasts",
        "audience": "Home gardeners and botany hobbyists",
    }
    score_low = tailoring_service.score_relevance(low_match)
    assert score_low["relevance_score"] == 1
