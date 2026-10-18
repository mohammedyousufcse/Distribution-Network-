"""Unit tests for Destination Recommender Engine and precision@10 benchmark."""

import pytest
from app.services.recommender_service import RecommenderService


def test_recommend_destinations_ranking():
    text = "Announcing our new open-source agent framework for LLM builders and Python developers."
    title = "High Scale Python Agents"
    tags = ["ai", "python", "agents"]

    recs = RecommenderService.recommend_destinations(
        text=text,
        title=title,
        tags=tags,
        audience_pillar="ai",
        is_promotional=False,
        limit=5,
    )

    assert len(recs) <= 5
    assert len(recs) > 0
    # Top recommendation should have highest rank and score
    top = recs[0]
    assert top["rank"] == 1
    assert top["fit_score"] > 0.0
    assert top["eligible"] is True
    assert "reason" in top


def test_recommend_hard_rule_filter_links():
    # If content has links, destinations with allow_links=False must be filtered/ineligible
    text = "Check out our site at https://incubrix.io for the latest updates."
    recs = RecommenderService.recommend_destinations(text=text, limit=20)
    for r in recs:
        if not r["eligible"] and "prohibits external links" in r["reason"]:
            assert r["fit_score"] == 0.0


def test_recommend_precision_benchmark():
    benchmark_res = RecommenderService.evaluate_precision_at_k(k=10)
    assert "mean_precision_at_k" in benchmark_res
    assert benchmark_res["mean_precision_at_k"] >= 0.40
    assert benchmark_res["test_samples_count"] >= 3
    assert len(benchmark_res["benchmark_details"]) == benchmark_res["test_samples_count"]
