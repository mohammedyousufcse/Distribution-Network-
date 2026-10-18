# Sources and References

This document records all third-party documentation, specifications, libraries, tutorials, and external materials referenced during the project, including versions and commercial-use licensing.

---

## 1. Core Frameworks & Specifications

1. **FastAPI Framework**
   - Version: $\ge$ 0.115.0
   - License: MIT (Permissive / Commercially usable)
   - URL: https://fastapi.tiangolo.com/
   - Usage: Application architecture, async routing, Pydantic response models, and OpenAPI 3.1 schema generation.

2. **OpenAPI 3.1.0 Specification**
   - License: Apache 2.0
   - URL: https://spec.openapis.org/oas/v3.1.0
   - Usage: REST API contract documentation (`openapi.yaml`), interactive Swagger UI (`/docs`), and JSON schema (`/openapi.json`).

3. **Pydantic & Pydantic Settings**
   - Version: $\ge$ 2.4.0
   - License: MIT
   - URL: https://docs.pydantic.dev/latest/
   - Usage: Data model validation, environment variable parsing, and type-safe configuration.

4. **HTTPX & HTTPX2 - Next Generation HTTP Clients**
   - Version: `httpx>=0.27.0`, `httpx2>=2.13.0`
   - License: BSD 3-Clause (Permissive / Commercially usable)
   - URL: https://www.python-httpx.org/
   - Usage: Synchronous and asynchronous HTTP requests across connectors, connection pooling, and `MockTransport` / `TestClient` in-memory ASGI transport.

5. **PyYAML**
   - Version: $\ge$ 6.0
   - License: MIT
   - URL: https://pyyaml.org/
   - Usage: Parsing configuration-driven `destinations.yaml` catalogue and outputting standardized `openapi.yaml`.

6. **Pytest Testing Framework**
   - Version: $\ge$ 8.3.0
   - License: MIT
   - URL: https://docs.pytest.org/
   - Usage: Test harness for unit, contract, drift, and integration test execution.

7. **Docker & Docker Compose**
   - License: Apache 2.0
   - URL: https://docs.docker.com/compose/
   - Usage: Container virtualization, health checks, and reproducible execution.

---

## 2. Connector API Specifications

1. **Discourse API Specification**
   - URL: https://docs.discourse.org/
   - Endpoints: `POST /posts.json`, `GET /posts/{id}.json`, `DELETE /posts/{id}.json`
   - Usage: Header-based authentication (`Api-Key`, `Api-Username`), topic creation, and reply formatting.

2. **Lemmy HTTP API Specification**
   - URL: https://join-lemmy.org/api/classes/LemmyHttp.html
   - Endpoints: `POST /api/v3/post`, `GET /api/v3/post`, `POST /api/v3/post/delete`
   - Usage: Community post creation, Bearer token authorization, and federated URL attachment.

3. **Dev.to / Forem REST API**
   - URL: https://developers.forem.com/api/v1
   - Endpoints: `POST /api/articles`, `GET /api/articles/{id}`, `PUT /api/articles/{id}`
   - Usage: `api-key` header authentication, markdown article publishing, and unpublish deletion strategy.

4. **Ghost Admin API v5 Specification**
   - URL: https://ghost.org/docs/admin-api/
   - Endpoints: `POST /ghost/api/admin/posts/`, `GET /ghost/api/admin/posts/{id}/`, `DELETE /ghost/api/admin/posts/{id}/`
   - Usage: Short-lived HS256 JWT generation using Admin hex credentials with `kid` and `aud: "/admin/"` claims.

5. **Generic HMAC-Signed Webhook Specification**
   - RFC: RFC 2104 (HMAC: Keyed-Hashing for Message Authentication), RFC 6234 (SHA-256)
   - Usage: Cryptographic request signing, timestamp replay prevention (<300s window), and constant-time string comparison (`hmac.compare_digest`).

6. **Mastodon REST API**
   - URL: https://docs.joinmastodon.org/methods/statuses/
   - Endpoints: `POST /api/v1/statuses`, `GET /api/v1/statuses/{id}`, `DELETE /api/v1/statuses/{id}`
   - Usage: OAuth 2.0 Bearer token authentication, status creation, idempotency forwarding, and error code translation.
