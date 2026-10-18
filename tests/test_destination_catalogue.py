"""
Tests for Configuration-Driven Multi-Destination Catalogue:
Proves that two or more destinations of the same connector type can use
different configuration values while sharing the same connector implementation.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.catalogue_service import catalogue_service, normalize_url

client = TestClient(app)


def test_url_normalization():
    assert normalize_url("https://Example.COM/api/v1/") == "https://example.com/api/v1"
    assert normalize_url("http://Lemmy:8536///") == "http://lemmy:8536"
    assert normalize_url(None) is None


def test_catalogue_loads_destinations():
    destinations = catalogue_service.list_destinations()
    assert len(destinations) >= 6
    dest_ids = [d["id"] for d in destinations]
    assert "discourse_dev_forum" in dest_ids
    assert "discourse_gaming_hub" in dest_ids
    assert "lemmy_technology" in dest_ids
    assert "lemmy_programming" in dest_ids


def test_same_connector_different_configurations():
    """
    Proves requirement: 'Add tests proving that two or more destinations of the same
    connector type can use different configuration values while sharing the same connector implementation.'
    """
    disc1 = catalogue_service.get_destination("discourse_dev_forum")
    disc2 = catalogue_service.get_destination("discourse_gaming_hub")

    # Both share the same connector key
    assert disc1["connector_key"] == "discourse"
    assert disc2["connector_key"] == "discourse"

    # Distinct base URLs
    assert disc1["base_url"] != disc2["base_url"]

    # Distinct posting rules
    policy1 = catalogue_service.get_policy("discourse_dev_forum")
    policy2 = catalogue_service.get_policy("discourse_gaming_hub")

    assert policy1.max_requests_per_window != policy2.max_requests_per_window
    assert policy1.weekly_frequency_cap != policy2.weekly_frequency_cap
    assert policy1.allow_self_promotion is False
    assert policy2.allow_self_promotion is True
    assert policy1.allow_links is True
    assert policy2.allow_links is False


def test_lemmy_destinations_different_instances():
    lem1 = catalogue_service.get_destination("lemmy_technology")
    lem2 = catalogue_service.get_destination("lemmy_programming")

    assert lem1["connector_key"] == "lemmy"
    assert lem2["connector_key"] == "lemmy"
    assert lem1["community_name"] != lem2["community_name"]
    assert lem1["base_url"] != lem2["base_url"]


def test_api_list_and_get_destinations():
    resp = client.get("/connector/v1/destinations")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 6

    # Filter by connector_key
    resp_lemmy = client.get("/connector/v1/destinations?connector_key=lemmy")
    assert resp_lemmy.status_code == 200
    data_lemmy = resp_lemmy.json()
    assert all(d["connector_key"] == "lemmy" for d in data_lemmy)

    # Get single destination
    resp_single = client.get("/connector/v1/destinations/discourse_dev_forum")
    assert resp_single.status_code == 200
    assert resp_single.json()["id"] == "discourse_dev_forum"

    # 404 for missing
    resp_missing = client.get("/connector/v1/destinations/non_existent_id")
    assert resp_missing.status_code == 404
