"""Basic test suite for health, readiness, and docs endpoints."""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_check_returns_healthy():
    """Verify GET /health returns 200 OK and expected status payload."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "service" in data
    assert "environment" in data


def test_readiness_check_returns_ready():
    """Verify GET /ready returns 200 OK and expected readiness status."""
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert "checks" in data
    assert data["checks"]["configuration"] == "ok"


def test_docs_and_openapi_accessible():
    """Verify Swagger UI docs at /docs and OpenAPI 3.1 schema are accessible."""
    docs_response = client.get("/docs")
    assert docs_response.status_code == 200

    openapi_response = client.get("/openapi.json")
    assert openapi_response.status_code == 200
    schema = openapi_response.json()
    assert schema["openapi"].startswith("3.1")
