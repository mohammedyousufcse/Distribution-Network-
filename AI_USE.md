# AI Use Log

This document records all generative AI assistance utilized during the development of the **Distribution: Long-Tail Destination Network** assessment project.

---

## Milestone 1: Project Foundation & Scaffolding

- **Date:** 2026-10-14
- **AI Tool / Model:** Gemini-powered Antigravity Coding Assistant
- **Task / Scope:**
  - Designed the initial folder architecture (`app/api`, `app/connectors`, `app/services`, `app/models`, `tests`).
  - Created base FastAPI app setup with `/health` and `/ready` probes.
  - Implemented environment-driven configuration with `pydantic-settings`.
  - Configured `Dockerfile` and `compose.yaml` for local containerization.
  - Generated initial test suite using `pytest` and FastAPI's `TestClient`.
- **Prompts & Instructions Given:**
  - Setup initial project foundation adhering to Python 3.11+, FastAPI, pytest, Docker, Docker Compose, and OpenAPI 3.1.
  - Enforce clean separation of concerns, no fake connector stubs, and strict environment configuration.
- **Human Verification & Modifications:**
  - Verified non-hardcoded configuration structure.
  - Verified OpenAPI 3.1 specification compliance.
  - Verified test coverage for `/health`, `/ready`, and `/docs`.

---

## Milestone 2: Connector Interface & Safe Mock Implementation

- **Date:** 2026-10-16
- **AI Tool / Model:** Gemini-powered Antigravity Coding Assistant
- **Task / Scope:**
  - Implemented abstract base interface `BaseConnector` in `app/connectors/base.py` (`validate`, `publish`, `get_status`, `delete`).
  - Created safe in-memory `MockConnector` in `app/connectors/mock.py` simulating local publication without external calls.
  - Exported connector classes in `app/connectors/__init__.py`.
  - Added unit test suite in `tests/test_connectors.py` covering validation, publication, status queries, and deletion.
- **Prompts & Instructions Given:**
  - Follow strict type annotations and abstract base class patterns.
  - Ensure zero external network calls and safe mock-only storage.
  - Validate non-empty dictionary text payloads.
- **Human Verification & Modifications:**
  - Ran `python -m pytest -v` with all 12 tests passing.
  - Confirmed `/health`, `/ready`, `/docs`, and OpenAPI 3.1 endpoints remain intact.

---

## Milestone 3: Connector REST API Integration

- **Date:** 2026-10-16
- **AI Tool / Model:** Gemini-powered Antigravity Coding Assistant
- **Task / Scope:**
  - Created `app/connectors/registry.py` to manage connector instances cleanly across requests.
  - Implemented `POST /connector/v1/{connector_key}/{method}` in `app/api/connector.py` supporting `validate`, `publish`, `get_status`, and `delete`.
  - Added request and response models with OpenAPI 3.1 documentation.
  - Registered route in `app/main.py` alongside `/health` and `/ready`.
  - Added 14 automated API tests in `tests/test_connector_api.py`.
- **Prompts & Instructions Given:**
  - Implement `POST /connector/v1/{connector_key}/{method}` for mock connector.
  - Return clear, structured responses and HTTP error status codes.
  - Ensure zero external network calls.
- **Human Verification & Modifications:**
  - Ran `python -m pytest -v` with all 26 tests passing.
  - Verified OpenAPI documentation and interactive `/docs` Swagger UI accessibility.

---

## Milestone 4: Destination Policy & Frequency Cap Layer

- **Date:** 2026-10-16
- **AI Tool / Model:** Gemini-powered Antigravity Coding Assistant
- **Task / Scope:**
  - Implemented `DestinationPolicy` model in `app/models/policy.py` with configurable text length limits and frequency caps.
  - Defined stable error codes `DESTINATION_SPEC_VIOLATION` and `FREQUENCY_CAP_EXCEEDED`.
  - Implemented `PolicyService` in `app/services/policy_service.py` with sliding window timestamp pruning for in-memory frequency capping.
  - Integrated policy enforcement directly into `POST /connector/v1/{connector_key}/{method}` in `app/api/connector.py`.
  - Created 10 automated unit and API integration tests in `tests/test_policy.py`.
- **Prompts & Instructions Given:**
  - Enforce text length limits and non-empty text validation.
  - Implement simple in-memory frequency-cap tracking with stable error codes.
  - Maintain all existing contracts and passing tests.
- **Human Verification & Modifications:**
  - Ran `python -m pytest -v` with all 36 tests passing.
  - Verified error codes and HTTP 400/429 status code handling.

---

## Milestone 5: Standardized Structured Error Handling & HTTP Status Mapping

- **Date:** 2026-10-16
- **AI Tool / Model:** Gemini-powered Antigravity Coding Assistant
- **Task / Scope:**
  - Created `app/models/errors.py` with stable error codes (`DESTINATION_SPEC_VIOLATION`, `FREQUENCY_CAP_EXCEEDED`, `AUTH_EXPIRED`, `RATE_LIMITED`, `QUOTA_EXHAUSTED`, `CONTENT_REJECTED`) and `ConnectorException` hierarchy.
  - Configured global exception handler in `app/main.py` for consistent JSON error serialization.
  - Enabled controlled error simulation in `MockConnector` for testing without external dependencies.
  - Added 14 unit and integration tests in `tests/test_errors.py`.
- **Prompts & Instructions Given:**
  - Standardize error responses to include error code, message, and detail.
  - Map errors to HTTP 400, 401, 403, and 429 status codes.
  - Maintain all existing contracts and passing tests.
- **Human Verification & Modifications:**
  - Ran `python -m pytest -v` with all 50 tests passing.
  - Verified that all error codes return expected HTTP statuses and JSON schemas.

---

## Milestone 6: Production Containerization & Live Docker Verification

- **Date:** 2026-10-16
- **AI Tool / Model:** Gemini-powered Antigravity Coding Assistant
- **Task / Scope:**
  - Hardened `Dockerfile` with non-root unprivileged `appuser`, layer caching, and built-in Python `HEALTHCHECK` querying `/health`.
  - Configured `compose.yaml` with variable defaults, quotes around YAML string values containing colons, port mapping `8000:8000`, and health checks.
  - Added `.dockerignore` to exclude virtual environment, `.pytest_cache`, `__pycache__`, and `.git` from image build context.
  - Fixed Python 3.11 typing import (`Optional`) in `app/connectors/mock.py`.
  - Executed live container build and run using `docker compose up --build -d`.
  - Verified live container health status (`healthy`) and queried `/health`, `/ready`, and `/docs` successfully.
  - Cleanly stopped and removed container resources with `docker compose down`.
- **Prompts & Instructions Given:**
  - Inspect Dockerfile, compose.yaml, requirements.txt, app/main.py, and .env.example.
  - Make project container-ready with healthcheck and 0.0.0.0 binding.
  - Do not claim Docker was verified if unavailable; if available, build and verify `/health`, `/ready`, and `/docs`.
- **Human Verification & Modifications:**
  - Ran `python -m pytest -v` with all 50 tests passing.
  - Built and started container with `docker compose up --build -d`.
  - Validated `/health` (`{"status":"healthy",...}`), `/ready` (`{"status":"ready",...}`), and `/docs` (`200 OK`).
  - Stopped containers cleanly using `docker compose down`.

---

## Milestone 7: POST Idempotency & Thread-Safe Duplicate Suppression

- **Date:** 2026-10-17
- **AI Tool / Model:** Gemini-powered Antigravity Coding Assistant
- **Task / Scope:**
  - Implemented `IdempotencyService` in `app/services/idempotency_service.py` with in-memory TTL caching and re-entrant thread synchronization (`threading.RLock`, `threading.Event`).
  - Added optional `Idempotency-Key` HTTP header to `POST /connector/v1/{connector_key}/publish` in `app/api/connector.py`.
  - Configured `IDEMPOTENCY_TTL_SECONDS` in `app/config.py`, `.env.example`, and `compose.yaml` (default: 300s).
  - Added `ERROR_CODE_IDEMPOTENCY_CONFLICT` (HTTP 409) and `IdempotencyConflictError` in `app/models/errors.py`.
  - Updated OpenAPI 3.1 documentation with `Idempotency-Key` header and 409 Conflict status.
  - Created 13 unit and integration tests in `tests/test_idempotency.py` and `tests/test_errors.py` covering first publication, duplicate replay, conflicting payloads, concurrency, TTL expiration, and unkeyed requests.
- **Prompts & Instructions Given:**
  - Accept optional `Idempotency-Key` header for publish operations.
  - Return original response for identical replay; return 409 Conflict for conflicting payload.
  - Guarantee concurrent requests cannot create duplicate posts.
  - Document in-memory limitation and configure TTL via environment variable.
- **Human Verification & Modifications:**
  - Ran `pytest -v` locally and inside Docker container: all 63 tests passed.
  - Verified live Swagger/OpenAPI 3.1 schema and live endpoints via curl/urllib queries.

---

## Milestone 8: Structured JSON Logging & Security Redaction

- **Date:** 2026-10-17
- **AI Tool / Model:** Gemini-powered Antigravity Coding Assistant
- **Task / Scope:**
  - Implemented `JSONFormatter` in `app/logging.py` using Python's standard `logging` library for single-line JSON formatting.
  - Added recursive credential redaction for passwords, API keys, access tokens, and Bearer authorization tokens.
  - Integrated structured logging across `app/api/connector.py` for operation start, operation success, policy validation failures, frequency-cap rejections, idempotency conflicts, and connector exceptions.
  - Configured `LOG_LEVEL` in `app/config.py`, `.env.example`, and `compose.yaml`.
  - Added 8 unit and integration tests in `tests/test_logging.py`.
- **Prompts & Instructions Given:**
  - Implement structured JSON logging using standard logging library.
  - Log operation start/completion, connector key, operation/method, duration_ms, and error code.
  - Stream logs to stdout for Docker Compose ingestion.
  - Redact sensitive credentials.
- **Human Verification & Modifications:**
  - Ran `docker compose exec api pytest -q`: all 71 tests passed.
  - Inspected live Docker container logs via `docker compose logs api` to confirm JSON formatting.

---

## Milestone 9: Asynchronous Background Jobs for Long-Running Operations

- **Date:** 2026-10-17
- **AI Tool / Model:** Gemini-powered Antigravity Coding Assistant
- **Task / Scope:**
  - Designed and implemented thread-safe in-memory `JobService` in `app/services/job_service.py` with `JobStatus` (`queued`, `running`, `succeeded`, `failed`), `JobRecord`, lock synchronization, and timestamps.
  - Implemented asynchronous publishing flow in `app/api/connector.py` powered by FastAPI `BackgroundTasks`.
  - Added `HTTP 202 Accepted` response with unique `job_id`, status, and `status_url` for async operations (triggered via `?async=true`, `Prefer: respond-async`, `{"async": true}`, or `simulate_delay >= 2.0`).
  - Implemented `GET /connector/v1/jobs/{job_id}` endpoint to query execution progress, completion latency (`duration_ms`), publication results, or structured failure errors.
  - Enforced pre-execution policy checks and frequency caps before job queueing to fast-fail invalid client inputs.
  - Preserved `Idempotency-Key` duplicate suppression: replaying the same key with identical payload returns the original `202 Accepted` and `job_id` without creating duplicate background tasks or posts; conflicting payloads return `HTTP 409 Conflict`.
  - Added 13 unit and integration tests in `tests/test_jobs.py`.
  - Updated `README.md` and OpenAPI 3.1 schema.
- **Prompts & Instructions Given:**
  - Implement background jobs for long-running operations (>2s) in IncuBrix Distribution Network.
  - Preserve all existing endpoints and synchronous quick operations.
  - Return HTTP 202 Accepted with a unique job ID.
  - Add status lookup endpoint (`queued`, `running`, `succeeded`, `failed`) storing results and errors.
  - Preserve policy validation, frequency caps, structured JSON errors, and POST Idempotency-Key duplicate suppression.
  - Use lightweight FastAPI BackgroundTasks; do not introduce Redis or paid services.
  - Document API, OpenAPI 3.1, and explicitly document that in-memory background processing is not durable across restarts.
- **Human Verification & Modifications:**
  - Rebuilt Docker image with `docker compose up -d --build`.
  - Executed complete test suite inside Docker: `docker compose exec api pytest -q` (all 84 tests passed).
  - Verified live OpenAPI 3.1 specification at `/openapi.json` and interactive Swagger docs at `/docs`.

---

## Milestone 10: Real Mastodon Destination Connector Implementation

- **Date:** 2026-10-17
- **AI Tool / Model:** Gemini-powered Antigravity Coding Assistant
- **Task / Scope:**
  - Created `app/connectors/mastodon.py` implementing `BaseConnector` using `httpx` for standard HTTPS operations (`POST /api/v1/statuses`, `GET /api/v1/statuses/{id}`, and `DELETE /api/v1/statuses/{id}`).
  - Added configuration support via `MASTODON_BASE_URL` and `MASTODON_ACCESS_TOKEN` in `app/config.py`, `.env.example`, and `compose.yaml`.
  - Registered connector under key `"mastodon"` in `app/connectors/registry.py` alongside `"mock"`.
  - Configured destination policy (500 character limit, 10 req/min frequency cap) in `app/services/policy_service.py`.
  - Mapped external Mastodon errors to structured exceptions (`AuthExpiredError` for 401, `RateLimitedError` for 429 with `Retry-After`, `ContentRejectedError` for 403 moderation, `ForbiddenError` for 403 scopes, and `NetworkError` for transport/timeout failures).
  - Added 24 comprehensive unit and API integration tests in `tests/test_mastodon_connector.py` covering publishing, retrieval, deletion, configuration validation, rate limits, timeouts, and idempotency.
  - Updated documentation in `README.md` and `SOURCES.md`.
- **Prompts & Instructions Given:**
  - Implement real Mastodon connector adhering to `BaseConnector` interface using `httpx`.
  - Configure URL and access token using environment variables; never hardcode secrets.
  - Implement publishing (`POST /api/v1/statuses`), status lookup (`GET /api/v1/statuses/{id}`), and deletion (`DELETE /api/v1/statuses/{id}`).
  - Map errors appropriately without classifying every 403 as content rejection.
  - Preserve all existing functionality (policy, frequency caps, idempotency, background jobs, logging).
  - Add automated tests with mocked HTTP responses; do not require real credentials for test runs.
  - Document permissions, testing against dedicated accounts, and limitation that live integration is pending real credentials.
- **Human Verification & Modifications:**
  - Executed `python -m pytest -q`: all 108 tests passed.
  - Rebuilt Docker container with `docker compose up -d --build`.
  - Ran full test suite inside Docker: `docker compose exec api pytest -v`.
  - Verified live endpoints `/health`, `/ready`, `/docs`, and `/openapi.json` (OpenAPI 3.1.0).

---

## Milestone 11: Assessment 4 Master Execution (P0 – P5)

- **Date:** 2026-10-17
- **AI Tool / Model:** Gemini-powered Antigravity Coding Assistant
- **Task / Scope:**
  - Created `REQUIREMENTS_AUDIT.md` performing gap analysis across all 28 must-have requirements.
  - Aligned error codes with Appendix A shared specifications (`DEST_SPEC_VIOLATION`, `DEST_RULE_FREQUENCY_CAP`, `CONNECTION_AUTH_EXPIRED`, `PLATFORM_RATE_LIMIT`, `PLATFORM_QUOTA_EXHAUSTED`, `PLATFORM_CONTENT_REJECTED`).
  - Implemented all 6 Core connectors:
    1. `DiscourseConnector` (`app/connectors/discourse.py`)
    2. `LemmyConnector` (`app/connectors/lemmy.py`)
    3. `DevToConnector` (`app/connectors/devto.py`)
    4. `GhostConnector` (`app/connectors/ghost.py`)
    5. `WebhookConnector` (`app/connectors/webhook.py`)
    6. `AssistedConnector` (`app/connectors/assisted.py`)
  - Created configuration-driven destination catalogue in `destinations.yaml` and `app/services/catalogue_service.py` supporting multi-destination sharing.
  - Expanded `PolicyService` into a multi-category posting-rules engine with weekly rolling caps, clock injection, link policy, self-promotion rules, and AI disclosure requirements.
  - Implemented safe retries and timeout reconciliation in `IdempotencyService` and verified zero duplicate posts.
  - Built repeatable 12-step certification workflow in `CertificationService` storing timestamped auditable JSON evidence in `EVIDENCE/`.
  - Added schema drift automated test in `tests/test_openapi_drift.py` and updated `openapi.yaml`.
  - Expanded test suite from 108 to **147 passing tests** with 0 failures.
  - Updated all documentation files (`REPORT.md`, `README.md`, `SOURCES.md`, `REQUIREMENTS_AUDIT.md`, `SUBMISSION_CHECKLIST.md`).
- **Prompts & Instructions Given:**
  - Execute Assessment 4 Master Execution prompt following strict non-negotiable priority order (P0 $\rightarrow$ P5).
  - Implement 6 Core connectors, multi-destination catalogue, posting-rules engine, safe retries, certification harness.
  - Maintain zero regressions on existing tests; do not delete or weaken tests.
  - Never fabricate test results or live credentials; use simulation mode and mock transports.
  - Keep secrets strictly out of code, git, logs, reports, and evidence.
- **Human Verification & Modifications:**
  - Executed full test suite inside Docker: `docker compose exec api pytest -v` (147 passed, 0 failed, 1 warning in 8.00s).
  - Verified genuine certification evidence generated in `EVIDENCE/`.
  - Verified OpenAPI 3.1 schema compliance and drift protection.










