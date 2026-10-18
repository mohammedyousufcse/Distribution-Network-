"""
Tests for Destination Certification Harness and Evidence Storage:
1. End-to-end certification probe across destination configurations.
2. Verification of cleanup deletion (within 10 minutes requirement).
3. Evidence storage in EVIDENCE/ directory.
4. HTTP API endpoint POST /connector/v1/destinations/{id}/certify.
"""

import asyncio
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.certification_service import certification_harness

client = TestClient(app)


def test_certification_harness_simulation_success():
    # Certify lemmy_technology destination in simulation mode
    result = asyncio.run(certification_harness.certify_destination("lemmy_technology", simulation=True))
    assert result["status"] == "SUCCESS"
    assert result["cleanup_verified"] is True
    assert result["destination_id"] == "lemmy_technology"
    assert result["steps"]["publish"]["ok"] is True
    assert result["steps"]["delete"]["ok"] is True

    # Verify evidence file was created on disk
    evidence_files = list(Path("EVIDENCE").glob("lemmy_technology_cert_*.json"))
    assert len(evidence_files) > 0


def test_certification_harness_devto_simulation():
    result = asyncio.run(certification_harness.certify_destination("devto_engineering", simulation=True))
    assert result["status"] == "SUCCESS"
    assert result["cleanup_verified"] is True
    assert result["steps"]["validate"]["ok"] is True


def test_certification_harness_missing_destination():
    result = asyncio.run(certification_harness.certify_destination("non_existent_destination", simulation=True))
    assert result["status"] == "FAILED"
    assert len(result["errors"]) > 0


def test_api_certify_destination_endpoint():
    resp = client.post("/connector/v1/destinations/discourse_dev_forum/certify?simulation=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert data["cleanup_verified"] is True
    assert data["steps"]["validate"]["ok"] is True
    assert data["steps"]["publish"]["ok"] is True
    assert data["steps"]["delete"]["ok"] is True
