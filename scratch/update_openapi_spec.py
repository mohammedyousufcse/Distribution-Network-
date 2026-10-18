import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import json
import urllib.request
import yaml

def generate_openapi_yaml():
    from app.main import app
    schema = app.openapi()

    # Explicitly ensure OpenAPI version is 3.1.0
    schema["openapi"] = "3.1.0"

    # Local development server
    schema["servers"] = [
        {
            "url": "http://localhost:8000",
            "description": "Local development server",
        }
    ]

    schema["info"] = {
        "title": "Distribution: Long-Tail Destination Network API",
        "description": (
            "Distribution: Long-Tail Destination Network - Foundation Service REST API specification covering health probes, "
            "background job tracking, connector manifest retrieval, configuration-driven multi-destination catalogue, automated certification harness, "
            "and destination connector operations across six Core connectors (Discourse, Lemmy, Dev.to, Ghost, HMAC Webhook, Assisted) "
            "plus Mock and Mastodon connectors."
        ),
        "version": "1.0.0",
    }

    schemas = schema.setdefault("components", {}).setdefault("schemas", {})

    schemas["ConnectorErrorResponse"] = {
        "title": "ConnectorErrorResponse",
        "type": "object",
        "description": "Consistent JSON error response model for connector and policy exceptions.",
        "required": ["error_code", "message", "detail"],
        "properties": {
            "error_code": {
                "type": "string",
                "description": (
                    "Machine-readable canonical error code: DEST_SPEC_VIOLATION, DEST_RULE_FREQUENCY_CAP, "
                    "CONNECTION_AUTH_EXPIRED, PLATFORM_RATE_LIMIT, PLATFORM_QUOTA_EXHAUSTED, PLATFORM_CONTENT_REJECTED, "
                    "IDEMPOTENCY_CONFLICT, NETWORK_ERROR, DESTINATION_ERROR."
                ),
                "example": "DEST_SPEC_VIOLATION",
            },
            "message": {"type": "string", "description": "Human-readable explanation of the error.", "example": "Content exceeds destination length limit."},
            "detail": {"type": "string", "description": "Detailed error message.", "example": "Content exceeds destination length limit."},
            "error": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "Error description for backward compatibility.", "example": "Content exceeds destination length limit."},
        },
    }

    schemas["DestinationCatalogueItem"] = {
        "title": "DestinationCatalogueItem",
        "type": "object",
        "description": "Configuration metadata for a registered destination.",
        "required": ["id", "name", "connector_key", "base_url"],
        "properties": {
            "id": {"type": "string", "example": "discourse_dev_forum"},
            "name": {"type": "string", "example": "Developer Community Forum"},
            "connector_key": {"type": "string", "example": "discourse"},
            "base_url": {"type": "string", "example": "https://meta.discourse.org"},
            "tier": {"type": "string", "example": "core"},
            "policy": {
                "type": "object",
                "properties": {
                    "max_length": {"type": "integer", "example": 20000},
                    "allow_links": {"type": "boolean", "example": True},
                    "allow_self_promotion": {"type": "boolean", "example": True},
                    "require_ai_disclosure": {"type": "boolean", "example": False},
                    "weekly_limit": {"type": "integer", "example": 5},
                },
            },
            "capabilities": {
                "type": "object",
                "properties": {
                    "validate": {"type": "boolean", "example": True},
                    "publish": {"type": "boolean", "example": True},
                    "get_status": {"type": "boolean", "example": True},
                    "delete": {"type": "boolean", "example": True},
                    "fetch_metrics": {"type": "boolean", "example": True},
                },
            },
        },
    }

    schemas["CertificationResult"] = {
        "title": "CertificationResult",
        "type": "object",
        "description": "Evidence and status record for a destination certification run.",
        "required": ["destination_id", "connector_key", "certified", "timestamp", "checks", "cleanup"],
        "properties": {
            "destination_id": {"type": "string", "example": "discourse_dev_forum"},
            "connector_key": {"type": "string", "example": "discourse"},
            "certified": {"type": "boolean", "example": True},
            "timestamp": {"type": "string", "example": "2026-10-17T22:00:00Z"},
            "duration_ms": {"type": "number", "example": 45.2},
            "evidence_file": {"type": "string", "example": "EVIDENCE/cert_discourse_dev_forum_20261017.json"},
            "checks": {
                "type": "object",
                "properties": {
                    "policy_rules": {"type": "boolean", "example": True},
                    "validation": {"type": "boolean", "example": True},
                    "publish": {"type": "boolean", "example": True},
                    "status_retrieval": {"type": "boolean", "example": True},
                },
            },
            "cleanup": {
                "type": "object",
                "properties": {
                    "deleted": {"type": "boolean", "example": True},
                    "within_10_min": {"type": "boolean", "example": True},
                },
            },
        },
    }

    schemas["ConnectorManifest"] = {
        "title": "ConnectorManifest",
        "type": "object",
        "description": "Standardized manifest descriptor for a destination connector.",
        "required": ["key", "version", "tier", "auth", "surfaces", "content_types", "specification_limits", "rate_limits", "capabilities", "error_map"],
        "properties": {
            "key": {"type": "string", "example": "discourse"},
            "version": {"type": "string", "example": "1.0.0"},
            "tier": {"type": "string", "example": "core"},
            "auth": {"type": "string", "example": "api_key"},
            "surfaces": {"type": "array", "items": {"type": "string"}},
            "content_types": {"type": "array", "items": {"type": "string"}},
            "specification_limits": {"type": "object"},
            "rate_limits": {"type": "object"},
            "capabilities": {"type": "object"},
            "error_map": {"type": "object"},
            "instance_parameter": {"type": "string", "example": "base_url"},
        },
    }

    # Enrich /connector/v1/{connector_key}/{method} path
    if "/connector/v1/{connector_key}/{method}" in schema.get("paths", {}):
        conn_op = schema["paths"]["/connector/v1/{connector_key}/{method}"]["post"]
        conn_op["parameters"] = [
            {
                "name": "connector_key",
                "in": "path",
                "required": True,
                "description": "Target destination connector key.",
                "schema": {
                    "type": "string",
                    "enum": ["mock", "mastodon", "discourse", "lemmy", "devto", "ghost", "webhook", "assisted", "hashnode", "slack", "mailchimp"],
                    "example": "discourse",
                },
            },
            {
                "name": "method",
                "in": "path",
                "required": True,
                "description": "Connector contract method to invoke.",
                "schema": {
                    "type": "string",
                    "enum": ["validate", "publish", "get_status", "delete", "fetch_metrics", "refresh_auth", "build_assist_pack"],
                    "example": "publish",
                },
            },
            {
                "name": "async",
                "in": "query",
                "required": False,
                "description": "Trigger asynchronous background processing (HTTP 202 Accepted).",
                "schema": {"type": "boolean", "example": False},
            },
            {
                "name": "Prefer",
                "in": "header",
                "required": False,
                "description": "RFC 7240 header; pass 'respond-async' for asynchronous background processing.",
                "schema": {"type": "string", "example": "respond-async"},
            },
            {
                "name": "Idempotency-Key",
                "in": "header",
                "required": False,
                "description": "Unique client idempotency token preventing duplicate publishing on network timeouts/retries.",
                "schema": {"type": "string", "example": "idem_123e4567-e89b-12d3-a456-426614174000"},
            },
        ]

    # Enrich /connector/v1/{connector_key}/manifest path
    if "/connector/v1/{connector_key}/manifest" in schema.get("paths", {}):
        man_op = schema["paths"]["/connector/v1/{connector_key}/manifest"]["get"]
        man_op["summary"] = "Retrieve connector manifest"
        man_op["description"] = "Returns the machine-readable connector manifest specifying limits, auth, tier, rate limits, and capabilities."
        man_op["parameters"] = [
            {
                "name": "connector_key",
                "in": "path",
                "required": True,
                "description": "Registered destination connector identifier.",
                "schema": {
                    "type": "string",
                    "enum": ["mock", "mastodon", "discourse", "lemmy", "devto", "ghost", "webhook", "assisted", "hashnode", "slack", "mailchimp"],
                    "example": "discourse",
                },
            }
        ]
        man_op["responses"]["200"] = {
            "description": "Connector manifest returned successfully.",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ConnectorManifest"}}},
        }

    # Enrich destinations paths
    if "/connector/v1/destinations" in schema.get("paths", {}):
        dest_op = schema["paths"]["/connector/v1/destinations"]["get"]
        dest_op["summary"] = "List destination catalogue"
        dest_op["description"] = "Returns all configured destinations loaded from the configuration-driven destinations catalogue."

    if "/connector/v1/destinations/{destination_id}/certify" in schema.get("paths", {}):
        cert_op = schema["paths"]["/connector/v1/destinations/{destination_id}/certify"]["post"]
        cert_op["summary"] = "Execute automated destination certification"
        cert_op["description"] = (
            "Executes the full 12-step certification workflow for a destination, verifying policy rules, validation, "
            "publishing, status retrieval, deletion, and storing timestamped evidence in EVIDENCE/."
        )
        cert_op["responses"]["200"] = {
            "description": "Certification executed and evidence stored.",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CertificationResult"}}},
        }

    # Write out YAML
    yaml_content = yaml.dump(schema, sort_keys=False, allow_unicode=True)
    with open("openapi.yaml", "w", encoding="utf-8") as f:
        f.write(yaml_content)
    print("Successfully generated openapi.yaml with", len(schema.get("paths", {})), "paths")

if __name__ == "__main__":
    generate_openapi_yaml()
