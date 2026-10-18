import os
import json
import yaml
import pytest
from fastapi.testclient import TestClient
from app.main import app

def test_openapi_spec_exists_and_valid():
    """Verify openapi.yaml exists, parses as valid YAML, and has OpenAPI 3.1.0."""
    assert os.path.exists("openapi.yaml"), "openapi.yaml must exist in the project root."
    with open("openapi.yaml", "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    assert spec.get("openapi") == "3.1.0", f"Expected OpenAPI 3.1.0, got {spec.get('openapi')}"
    assert "paths" in spec, "openapi.yaml must contain paths"
    assert "/connector/v1/{connector_key}/{method}" in spec["paths"]
    assert "/connector/v1/{connector_key}/manifest" in spec["paths"]
    assert "/connector/v1/destinations" in spec["paths"]
    assert "/connector/v1/destinations/{destination_id}/certify" in spec["paths"]

def test_no_openapi_drift_with_live_app():
    """Verify that all routes defined in FastAPI app are documented in openapi.yaml without missing paths."""
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    live_schema = response.json()

    with open("openapi.yaml", "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    live_paths = set(live_schema.get("paths", {}).keys())
    spec_paths = set(spec.get("paths", {}).keys())

    # Ensure no routes exist in FastAPI that are missing from openapi.yaml
    missing_in_spec = live_paths - spec_paths
    assert not missing_in_spec, f"Found undocumented endpoints in openapi.yaml: {missing_in_spec}"

    # Verify key methods for connector dispatch endpoint
    conn_path_ops = spec["paths"]["/connector/v1/{connector_key}/{method}"]
    assert "post" in conn_path_ops

    # Check connector_key enum includes core connectors
    post_params = {p["name"]: p for p in conn_path_ops["post"]["parameters"]}
    assert "connector_key" in post_params
    assert "method" in post_params

    connector_enums = post_params["connector_key"]["schema"].get("enum", [])
    for expected in ["discourse", "lemmy", "devto", "ghost", "webhook", "assisted", "mock", "mastodon"]:
        assert expected in connector_enums, f"Connector enum missing {expected}"
